import json
import logging
import os
import re
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# DATEV "Staatsangehörigkeitsschlüssel" (DEÜV / Destatis-BEV) keyed by ISO 3166-1
# alpha-2 (= Odoo res.country.code). Loaded once from the shipped JSON mapping.
_COUNTRY_OF_BIRTH_MAPPING = None


def _country_of_birth_code(iso_alpha2):
    """Return the 3-digit DATEV country-of-birth key for an ISO alpha-2 code, or None."""
    global _COUNTRY_OF_BIRTH_MAPPING
    if _COUNTRY_OF_BIRTH_MAPPING is None:
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "datev_country_of_birth_mapping.json",
        )
        try:
            with open(path, encoding="utf-8") as fh:
                _COUNTRY_OF_BIRTH_MAPPING = json.load(fh).get("mapping", {})
        except Exception as exc:  # pragma: no cover - defensive
            _logger.error("DATEV: could not load country_of_birth mapping: %s", exc)
            _COUNTRY_OF_BIRTH_MAPPING = {}
    return _COUNTRY_OF_BIRTH_MAPPING.get((iso_alpha2 or "").upper())


# Accepted address country codes. The hr:exchange address.country field takes
# ISO 3166-1 alpha-2 (identity passthrough of Odoo res.country.code) — NOT the
# alphabetic DEÜV-LDKZ that the OpenAPI enum suggests. We validate against the
# accepted set and pass the code through unchanged.
_ADDRESS_COUNTRY_ACCEPT = None


def _address_country_code(iso_alpha2):
    """Return the (upper-cased) ISO alpha-2 code if DATEV accepts it for addresses, else None."""
    global _ADDRESS_COUNTRY_ACCEPT
    if _ADDRESS_COUNTRY_ACCEPT is None:
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "datev_address_country_accept_list.json",
        )
        try:
            with open(path, encoding="utf-8") as fh:
                _ADDRESS_COUNTRY_ACCEPT = set(json.load(fh).get("accepted_iso_alpha2", []))
        except Exception as exc:  # pragma: no cover - defensive
            _logger.error("DATEV: could not load address country accept list: %s", exc)
            _ADDRESS_COUNTRY_ACCEPT = set()
    code = (iso_alpha2 or "").upper()
    return code if code in _ADDRESS_COUNTRY_ACCEPT else None

_DATEV_REQUIRED_FIELDS = {
    "birthday": "Geburtsdatum",
    "gender": "Geschlecht",
    "ssnid": "SV-Nummer",
    "datev_personnel_number": "Personalnummer (DATEV)",
    "datev_tax_class": "Steuerklasse",
    "datev_tax_id_number": "Steueridentifikationsnummer",
    "datev_health_insurance_name": "Krankenkasse",
    "datev_health_insurance_type": "Versicherungsart",
}

# All fields whose change should trigger an automatic sync when sync is enabled.
_DATEV_SYNC_FIELDS = frozenset(_DATEV_REQUIRED_FIELDS) | {
    "name",
    "marital",
    "children",
    "place_of_birth",
    "country_of_birth",
    "datev_church_tax",
    "datev_cost_center",
    "datev_child_allowance",
    "datev_employment_type",
    "datev_flat_rate_tax",
    "datev_si_nursing",
    "datev_si_pension",
    "datev_si_unemployment",
    "datev_si_childless_surcharge",
    "private_street",
    "private_city",
    "private_zip",
    "private_country_id",
    "bank_account_id",
    "datev_employment_start",
    "departure_date",
    "datev_weekly_working_hours",
    "datev_employee_type",
    "datev_vacation_days",
    "datev_payment_method",
    "job_id",
}

# DATEV hr:exchange job lifecycle. The API documents `state` only as a free string
# (observed initial value: "accepted"). We match terminal tokens explicitly and treat
# any unknown/in-progress state as still pending, so a job is never prematurely closed.
_JOB_SUCCESS_STATES = {"succeeded", "success", "successful", "completed", "done", "finished"}
_JOB_FAILURE_STATES = {"failed", "failure", "rejected", "error", "errored", "cancelled", "canceled"}


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # ── Sync status ─────────────────────────────────────────────────────────
    datev_sync_created = fields.Boolean(
        string="In DATEV angelegt",
        groups="hr.group_hr_user",
        help="Intern: Gibt an, ob dieser Mitarbeiter bereits per POST in DATEV LODAS angelegt wurde. "
             "Wird automatisch beim ersten erfolgreichen Transfer gesetzt.",
    )
    datev_sync_enabled = fields.Boolean(
        string="DATEV Cloud Sync aktiv",
        groups="hr.group_hr_user",
        help="Bei aktiver Synchronisation wird dieser Mitarbeiter nach jeder "
             "Änderung an einem DATEV-relevanten Feld automatisch übertragen.",
    )
    datev_last_sync = fields.Datetime(
        string="Letzte Synchronisation",
        readonly=True,
        groups="hr.group_hr_user",
    )
    datev_sync_error = fields.Text(
        string="Sync-Fehler",
        readonly=True,
        groups="hr.group_hr_user",
    )
    datev_sync_dirty = fields.Boolean(
        string="DATEV Sync ausstehend",
        copy=False,
        groups="hr.group_hr_user",
        help="Intern: Es gibt Änderungen, die noch nicht an DATEV übertragen "
             "wurden. Ein Sammel-Cron überträgt gebündelt (Debounce).",
    )
    datev_job_id = fields.Char(
        string="DATEV Job-ID",
        readonly=True,
        copy=False,
        groups="hr.group_hr_user",
    )
    datev_job_phase = fields.Selection(
        [("fetch", "Fetch (Read before write)"), ("push", "Push")],
        string="DATEV Job-Phase",
        readonly=True,
        copy=False,
        groups="hr.group_hr_user",
        help="fetch = Pflicht-Lesevorgang vor Anlage/Änderung; "
             "push = eigentliche Übertragung.",
    )
    datev_job_state = fields.Selection(
        [("pending", "Pending"), ("succeeded", "Succeeded"), ("failed", "Failed")],
        string="DATEV Job-Status",
        readonly=True,
        copy=False,
        groups="hr.group_hr_user",
    )
    datev_job_error = fields.Text(
        string="DATEV Job-Fehler",
        readonly=True,
        copy=False,
        groups="hr.group_hr_user",
    )
    datev_job_created_at = fields.Datetime(
        string="DATEV Job erstellt am",
        readonly=True,
        copy=False,
        groups="hr.group_hr_user",
    )
    datev_job_last_poll = fields.Datetime(
        string="DATEV Job zuletzt abgefragt",
        readonly=True,
        copy=False,
        groups="hr.group_hr_user",
    )

    # ── Allgemein ───────────────────────────────────────────────────────────
    datev_personnel_number = fields.Char(
        string="Personalnummer (DATEV)",
        groups="hr.group_hr_user",
        help="Eindeutige Personalnummer in DATEV LODAS / Lohn und Gehalt.",
    )
    datev_cost_center = fields.Char(
        string="Kostenstelle",
        groups="hr.group_hr_user",
    )

    # ── Steuer ──────────────────────────────────────────────────────────────
    datev_tax_class = fields.Selection(
        [("1", "I"), ("2", "II"), ("3", "III"), ("4", "IV"), ("5", "V"), ("6", "VI")],
        string="Steuerklasse",
        groups="hr.group_hr_user",
    )
    datev_tax_id_number = fields.Char(
        string="Steueridentifikationsnummer",
        groups="hr.group_hr_user",
        help="11-stellige persönliche Steuer-ID (nicht die USt-IdNr.).",
    )
    datev_church_tax = fields.Selection(
        [
            ("ohne", "Keine Kirchensteuer"),
            ("ev", "Evangelisch (ev)"),
            ("rk", "Römisch-Katholisch (rk)"),
            ("lt", "Lutherisch (lt)"),
            ("ak", "Alt-Katholisch (ak)"),
            ("is", "Islamisch (is)"),
            ("jd", "Jüdisch (jd)"),
            ("andere", "Andere"),
        ],
        string="Konfession / Kirchensteuer",
        groups="hr.group_hr_user",
    )
    datev_employment_type = fields.Selection(
        [
            ("1", "1 – Erstes/Hauptdienstverhältnis"),
            ("2", "2 – Weiteres Dienstverhältnis"),
        ],
        string="Beschäftigungsart (Steuer)",
        default="1",
        groups="hr.group_hr_user",
        help="DATEV taxation.employment_type. 1 = erstes Dienstverhältnis (Hauptarbeitgeber), "
             "2 = weiteres Dienstverhältnis (i. d. R. Steuerklasse VI).",
    )
    datev_flat_rate_tax = fields.Selection(
        [
            ("0", "0 – Keine Pauschalierung"),
            ("1", "1 – Pauschalierung"),
            ("2", "2 – Pauschalierung (besondere)"),
        ],
        string="Pauschalsteuer",
        default="0",
        groups="hr.group_hr_user",
        help="DATEV taxation.flat_rate_tax. Im Zweifel mit dem Steuerberater abstimmen.",
    )

    # ── Sozialversicherung ──────────────────────────────────────────────────
    datev_health_insurance_name = fields.Char(
        string="Betriebsnr. Krankenkasse",
        groups="hr.group_hr_user",
        help="8-stellige Betriebsnummer der Krankenkasse (z. B. 87880235). "
             "Wird als company_number_of_health_insurer an DATEV übermittelt.",
    )
    datev_health_insurance_type = fields.Selection(
        [("gkv", "GKV – Gesetzlich (Beitragsklasse 1)"), ("pkv", "PKV – Privat (Beitragsklasse 9)")],
        string="Versicherungsart",
        groups="hr.group_hr_user",
    )
    datev_child_allowance = fields.Float(
        string="Kinderfreibetrag",
        digits=(4, 1),
        groups="hr.group_hr_user",
        help="z. B. 0.5 je Kind bei gemeinsamer Veranlagung.",
    )
    datev_si_nursing = fields.Selection(
        [
            ("0", "0 – Kein Beitrag"),
            ("1", "1 – Voller Beitrag"),
            ("2", "2 – Halber Beitrag"),
        ],
        string="Beitragsklasse Pflegevers.",
        default="1",
        groups="hr.group_hr_user",
        help="DATEV contribution_class_nursing_insurance.",
    )
    datev_si_pension = fields.Selection(
        [
            ("0", "0 – Kein Beitrag"),
            ("1", "1 – Voller Beitrag"),
            ("3", "3 – Halber Beitrag"),
            ("5", "5 – Pauschalbeitrag"),
        ],
        string="Beitragsklasse Rentenvers.",
        default="1",
        groups="hr.group_hr_user",
        help="DATEV contribution_class_pension_insurance.",
    )
    datev_si_unemployment = fields.Selection(
        [
            ("0", "0 – Kein Beitrag"),
            ("1", "1 – Voller Beitrag"),
            ("2", "2 – Halber Beitrag"),
        ],
        string="Beitragsklasse Arbeitslosenvers.",
        default="1",
        groups="hr.group_hr_user",
        help="DATEV contribution_class_unemployment_insurance.",
    )
    datev_si_childless_surcharge = fields.Boolean(
        string="Kinderlosen-Zuschlag (PV)",
        default=True,
        groups="hr.group_hr_user",
        help="Zusätzlicher Beitrag zur Pflegeversicherung für Kinderlose (ab 23 J.). "
             "Aktiviert = Zuschlag wird berücksichtigt (DATEV-Feld "
             "is_additional_contribution_..._childless_ignored = false).",
    )

    # ── Beschäftigung & Vergütung ────────────────────────────────────────────
    datev_employment_start = fields.Date(
        string="Eintrittsdatum (DATEV)",
        groups="hr.group_hr_user",
        help="Beschäftigungsbeginn. Wird als employment_periods."
             "date_of_commencement_of_employment übertragen. Das Austrittsdatum "
             "wird – falls gesetzt – aus dem Standard-Feld 'Austrittsdatum' übernommen.",
    )
    datev_weekly_working_hours = fields.Float(
        string="Wochenarbeitszeit",
        digits=(4, 2),
        groups="hr.group_hr_user",
        help="Regelmäßige wöchentliche Arbeitszeit in Stunden (0–99). "
             "DATEV activity.weekly_working_hours.",
    )
    datev_employee_type = fields.Selection(
        [
            ("101", "101 – Sozialversicherungspflichtig Beschäftigte"),
            ("102", "102 – Auszubildende"),
            ("103", "103 – Beschäftigte in Altersteilzeit"),
            ("104", "104"),
            ("105", "105 – Praktikanten"),
            ("106", "106 – Werkstudenten"),
            ("107", "107"),
            ("108", "108"),
            ("109", "109 – Geringfügig entlohnt (Minijob)"),
            ("110", "110 – Kurzfristig Beschäftigte"),
            ("111", "111"),
            ("112", "112"),
            ("113", "113"),
            ("114", "114"),
            ("116", "116"),
            ("117", "117"),
            ("118", "118"),
            ("119", "119"),
            ("120", "120"),
            ("121", "121"),
            ("122", "122"),
            ("123", "123"),
            ("124", "124"),
            ("127", "127 – Freiwilligendienst (BFD/FSJ/FÖJ)"),
            ("190", "190 – Nur Unfallversicherung"),
            ("900", "900"),
        ],
        string="Personengruppe (SV)",
        default="101",
        groups="hr.group_hr_user",
        help="SV-Personengruppenschlüssel. DATEV activity.employee_type. "
             "101 = sozialversicherungspflichtig Beschäftigte (Standardfall).",
    )
    datev_vacation_days = fields.Float(
        string="Urlaubsanspruch (Tage/Jahr)",
        digits=(3, 1),
        groups="hr.group_hr_user",
        help="Jahresurlaubsanspruch in Tagen (0–99,5). "
             "DATEV vacation_entitlement.basic_vacation_entitlement.",
    )
    datev_payment_method = fields.Selection(
        [
            ("1", "1 – Überweisung"),
            ("4", "4 – Scheck"),
            ("5", "5 – Barauszahlung"),
        ],
        string="Zahlungsweise",
        default="1",
        groups="hr.group_hr_user",
        help="DATEV payment_method. Im Zweifel mit dem Steuerberater abstimmen.",
    )

    # ── Sync logic ──────────────────────────────────────────────────────────

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("_datev_sync_in_progress") and (
            _DATEV_SYNC_FIELDS & set(vals.keys())
        ):
            # Debounce: only mark as dirty — a collecting cron bundles several
            # rapid edits (and several employees) into ONE DATEV transfer
            # instead of firing a job per save.
            to_sync = self.filtered("datev_sync_enabled")
            if to_sync:
                to_sync.with_context(_datev_sync_in_progress=True).write(
                    {"datev_sync_dirty": True}
                )
        return result

    @api.model
    def _cron_datev_sync_dirty(self):
        dirty = self.search([
            ("datev_sync_dirty", "=", True),
            ("datev_sync_enabled", "=", True),
            # Don't start a new cycle while a job for this employee is running.
            ("datev_job_state", "!=", "pending"),
        ])
        if dirty:
            dirty.with_context(_datev_sync_in_progress=True)._action_datev_sync()

    def datev_get_missing_required_fields(self):
        """Return list of human-readable labels for unfilled required fields."""
        self.ensure_one()
        return [
            label
            for fname, label in _DATEV_REQUIRED_FIELDS.items()
            if not getattr(self, fname, False)
        ]

    def _action_datev_sync(self):
        """Start a DATEV sync cycle for these employees.

        DATEV hr:exchange mandates (interface requirements):
        1. Authorization check (GET /clients/{id}) before any transfer.
        2. A complete READ before any creation/modification — implemented as an
           async fetch job; the actual POST/PUT happens when the fetch result
           is available (see _poll_datev_hr_jobs / _continue_after_fetch).
        3. After every creation/modification a job status + result check.
        """
        ready = self.browse()
        for emp in self:
            missing = emp.datev_get_missing_required_fields()
            if missing:
                error = "Fehlende Pflichtfelder: " + ", ".join(missing)
                emp.write({"datev_sync_error": error, "datev_sync_dirty": False})
                _logger.warning(
                    "DATEV sync skipped for employee %s (%d): %s",
                    emp.name, emp.id, error,
                )
                continue
            ready |= emp

        from odoo.addons.datev_connector.services.datev_api import DatevApiService
        Settings = self.env["res.config.settings"]

        for company in ready.mapped(lambda e: e.company_id or self.env.company):
            emps = ready.filtered(lambda e: (e.company_id or self.env.company) == company)
            try:
                client_id = company.datev_get_client_id()
                service = DatevApiService(self.env, Settings._get_datev_config(company))
                # MUST 1: authorization check before data transfer
                service.hr_exchange_get_client(client_id)
                # MUST 2: read before write — async fetch of all employees
                reference_date = fields.Date.today().strftime("%Y-%m")
                job = service.hr_exchange_create_fetch_job(client_id, reference_date)
            except Exception as exc:
                emps.write({"datev_sync_error": str(exc)[:1000]})
                _logger.error("DATEV hr:exchange sync start failed (%s): %s", company.name, exc)
                continue
            emps.write({
                "datev_sync_dirty": False,
                "datev_sync_error": False,
                "datev_job_id": job.get("id"),
                "datev_job_phase": "fetch",
                "datev_job_state": "pending",
                "datev_job_error": False,
                "datev_job_created_at": fields.Datetime.now(),
                "datev_job_last_poll": False,
            })
            _logger.info(
                "DATEV hr:exchange fetch job %s started for %d employee(s) of %s",
                job.get("id"), len(emps), company.name,
            )

    def _build_hr_exchange_payload(self):
        """Build the hr:exchange JSON payload for a single employee (self.ensure_one())."""
        self.ensure_one()

        # ── Name splitting: "Maria Schmidt" → first_name="Maria", surname="Schmidt" ──
        name_parts = (self.name or "").strip().split()
        surname = name_parts[-1] if name_parts else "Unbekannt"
        first_name = " ".join(name_parts[:-1]) if len(name_parts) > 1 else None

        # ── Gender ──────────────────────────────────────────────────────────
        gender_map = {"male": "M", "female": "W", "other": "D"}
        sex = gender_map.get(self.gender or "", "D")

        # ── Church tax denomination (only values the DATEV API accepts) ──────
        _VALID_DENOMINATION = {
            "ak", "ev", "fa", "fb", "fg", "fm", "fr", "fs",
            "ib", "ih", "il", "is", "iw", "jd", "jh", "lt", "rf", "rk",
        }
        denomination = self.datev_church_tax if self.datev_church_tax in _VALID_DENOMINATION else None

        # ── Personnel number must be integer 1–99999 ─────────────────────────
        try:
            personnel_number = int(self.datev_personnel_number or "0")
            if not (1 <= personnel_number <= 99999):
                raise ValueError()
        except (ValueError, TypeError):
            raise UserError(
                f"Ungültige Personalnummer '{self.datev_personnel_number}' — "
                "muss eine Ganzzahl zwischen 1 und 99999 sein."
            )

        # ── Health insurance contribution class mapping ───────────────────────
        # GKV (gesetzlich) → Beitragsklasse 1; PKV (privat) → Beitragsklasse 9
        health_class_map = {"gkv": 1, "pkv": 9}
        health_contrib = health_class_map.get(self.datev_health_insurance_type or "", 1)

        # ── Build payload ────────────────────────────────────────────────────
        payload = {
            "surname": surname,
            "personnel_number": personnel_number,
        }
        if first_name:
            payload["first_name"] = first_name

        personal_data = {"sex": sex}
        if self.birthday:
            personal_data["date_of_birth"] = self.birthday.strftime("%Y-%m-%d")
        if self.ssnid:
            personal_data["social_security_number"] = self.ssnid
        if self.place_of_birth:
            personal_data["place_of_birth"] = self.place_of_birth[:34]
        if self.country_of_birth:
            datev_country = _country_of_birth_code(self.country_of_birth.code)
            if not datev_country:
                raise UserError(
                    f"Kein DATEV-Staatsangehörigkeitsschlüssel für Geburtsland "
                    f"'{self.country_of_birth.name}' ({self.country_of_birth.code}) hinterlegt. "
                    "Bitte Mapping ergänzen oder Geburtsland korrigieren."
                )
            personal_data["country_of_birth"] = datev_country
        payload["personal_data"] = personal_data

        tax_card = {}
        if self.datev_tax_class:
            tax_card["tax_class"] = self.datev_tax_class
        if denomination:
            tax_card["denomination"] = denomination
        if self.datev_child_allowance:
            tax_card["child_tax_allowances"] = self.datev_child_allowance
        if tax_card:
            payload["tax_card"] = tax_card

        taxation = {
            "employment_type": int(self.datev_employment_type or "1"),
            "flat_rate_tax": int(self.datev_flat_rate_tax or "0"),
        }
        if self.datev_tax_id_number:
            taxation["tax_identification_number"] = self.datev_tax_id_number
        payload["taxation"] = taxation

        social_insurance = {
            "contribution_class_health_insurance": health_contrib,
            "contribution_class_nursing_insurance": int(self.datev_si_nursing or "1"),
            "contribution_class_pension_insurance": int(self.datev_si_pension or "1"),
            "contribution_class_unemployment_insurance": int(self.datev_si_unemployment or "1"),
            # Odoo field is "Zuschlag berücksichtigen"; DATEV field is "...ignored" → invert.
            "is_additional_contribution_to_nursing_insurance_for_childless_ignored":
                not self.datev_si_childless_surcharge,
        }
        if self.datev_health_insurance_name:
            social_insurance["company_number_of_health_insurer"] = self.datev_health_insurance_name[:8]
        payload["social_insurance"] = social_insurance

        # ── Activity (cost center, working hours, employee type, job title) ──────
        activity = {}
        if self.datev_cost_center:
            activity["individual_cost_center_id"] = self.datev_cost_center[:13]
        if self.datev_weekly_working_hours:
            activity["weekly_working_hours"] = self.datev_weekly_working_hours
        if self.datev_employee_type:
            activity["employee_type"] = self.datev_employee_type
        occupational_title = self._format_occupational_title(
            self.job_id.name if self.job_id else ""
        )
        if occupational_title:
            activity["occupational_title"] = occupational_title
        if activity:
            payload["activity"] = activity

        # ── Employment period (commencement / termination) ──────────────────────
        if self.datev_employment_start:
            period = {
                "date_of_commencement_of_employment":
                    self.datev_employment_start.strftime("%Y-%m-%d"),
            }
            if self.departure_date:
                period["date_of_termination_of_employment"] = \
                    self.departure_date.strftime("%Y-%m-%d")
            payload["employment_periods"] = [period]

        # ── Payment method & vacation entitlement ───────────────────────────────
        if self.datev_payment_method:
            payload["payment_method"] = self.datev_payment_method
        if self.datev_vacation_days:
            payload["vacation_entitlement"] = {
                "basic_vacation_entitlement": self.datev_vacation_days,
            }

        # ── Address (optional; only sent when country + postal_code are present) ──
        addr = {}
        if self.private_street:
            street, house = self._split_street_house(self.private_street)
            addr["street"] = street[:34]
            if house:
                addr["house_number"] = house[:9]
        if self.private_city:
            addr["city"] = self.private_city[:34]
        if self.private_zip:
            addr["postal_code"] = self.private_zip[:10]
        if self.private_country_id:
            country_code = _address_country_code(self.private_country_id.code)
            if country_code:
                addr["country"] = country_code
            else:
                _logger.warning(
                    "DATEV: address skipped for %s — country %s (%s) not in DATEV accept list.",
                    self.name, self.private_country_id.name, self.private_country_id.code,
                )
        # DATEV Address schema requires both country and postal_code.
        if addr.get("country") and addr.get("postal_code"):
            payload["address"] = addr

        # ── Bank account (IBAN / BIC) ────────────────────────────────────────
        bank = self.bank_account_id
        if bank and bank.acc_number:
            account = {"iban": bank.acc_number.replace(" ", "").upper()}
            bic = bank.bank_id.bic if bank.bank_id else None
            if bic:
                account["bic"] = bic.replace(" ", "").upper()
            payload["account"] = account

        return payload

    @staticmethod
    def _split_street_house(street):
        """Split 'Roonstr. 101' → ('Roonstr.', '101'). House part may be None."""
        m = re.match(r"^(.*?)[\s,]+(\d+\s*[a-zA-Z]?)$", (street or "").strip())
        if m:
            return m.group(1).strip(), m.group(2).replace(" ", "")
        return (street or "").strip(), None

    @staticmethod
    def _format_occupational_title(title):
        """Format occupational_title for DATEV: sent as-is, only capped at 30 chars.

        The OpenAPI spec declares a restrictive pattern (^[a-zA-Z0-9_]*$) but its own
        examples use spaces and umlauts, so we follow the examples and send raw text.
        """
        return (title or "").strip()[:30]

    def action_datev_refresh_job_status(self):
        pending = self.filtered(lambda e: e.datev_job_id and e.datev_job_state == "pending")
        if not pending:
            raise UserError("Keine offenen DATEV-Jobs für die ausgewählten Mitarbeiter.")
        polled = pending._poll_datev_hr_jobs()
        if not polled:
            # DATEV poll cadence: at most one status request per minute per job.
            raise UserError(
                "DATEV erlaubt höchstens eine Statusabfrage pro Minute. "
                "Bitte in Kürze erneut versuchen."
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": "DATEV Job-Status", "message": "Status aktualisiert.", "type": "info"},
        }

    @api.model
    def _cron_poll_datev_hr_jobs(self):
        pending = self.search([("datev_job_id", "!=", False), ("datev_job_state", "=", "pending")])
        if pending:
            pending._poll_datev_hr_jobs()

    @staticmethod
    def _extract_job_errors(result):
        """Flatten a DATEV job-result error list into a single string (or False)."""
        errors = result.get("errors") or result.get("messages") or []
        if isinstance(errors, dict):
            errors = [errors]
        if not isinstance(errors, list):
            return str(errors) or False
        parts = []
        for e in errors:
            if isinstance(e, dict):
                msg = (
                    e.get("client_message") or e.get("message") or e.get("technical_message")
                    or e.get("detail") or e.get("description") or ""
                )
                code = e.get("code") or e.get("id") or e.get("error_code") or ""
                parts.append(f"[{code}] {msg}".strip() if code else (msg or str(e)))
            else:
                parts.append(str(e))
        return "\n".join(p for p in parts if p) or False

    # Poll cadence mandated by the hr:exchange interface requirements:
    # first status request no earlier than 60 s after job creation, at most one
    # request per minute, abort after 15 min without a state change.
    _POLL_MIN_AGE = timedelta(seconds=60)
    _POLL_INTERVAL = timedelta(seconds=60)
    _POLL_TIMEOUT = timedelta(minutes=15)

    def _poll_datev_hr_jobs(self):
        """Poll pending jobs (grouped per company+job) honoring the mandated
        cadence and drive the fetch→push state machine. Returns the number of
        jobs actually polled."""
        from odoo.addons.datev_connector.services.datev_api import DatevApiService
        Settings = self.env["res.config.settings"]
        now = fields.Datetime.now()

        groups = {}
        for emp in self:
            if emp.datev_job_state != "pending" or not emp.datev_job_id:
                continue
            key = ((emp.company_id or self.env.company).id, emp.datev_job_id)
            groups.setdefault(key, self.browse())
            groups[key] |= emp

        polled = 0
        for (company_id, job_id), emps in groups.items():
            company = self.env["res.company"].browse(company_id)
            created_dates = [d for d in emps.mapped("datev_job_created_at") if d]
            poll_dates = [d for d in emps.mapped("datev_job_last_poll") if d]
            created_at = min(created_dates) if created_dates else False
            last_poll = max(poll_dates) if poll_dates else False

            if created_at and now - created_at < self._POLL_MIN_AGE:
                continue
            if last_poll and now - last_poll < self._POLL_INTERVAL:
                continue
            if created_at and now - created_at > self._POLL_TIMEOUT:
                emps.write({
                    "datev_job_state": "failed",
                    "datev_job_error": "Zeitüberschreitung (15 min) — Status unbekannt, "
                                       "bitte manuell in DATEV prüfen.",
                })
                _logger.error("DATEV hr:exchange job %s timed out after 15 min.", job_id)
                continue

            emps.write({"datev_job_last_poll": now})
            polled += 1
            try:
                client_id = company.datev_get_client_id()
                service = DatevApiService(self.env, Settings._get_datev_config(company))
                status = service.hr_exchange_job_status(client_id, job_id)
            except Exception as exc:
                _logger.warning("DATEV hr:exchange job poll failed (%s): %s", job_id, exc)
                continue

            _logger.info("DATEV hr:exchange job %s raw status: %s", job_id, status)
            state = (status.get("state") or status.get("status") or "").lower()

            if state in _JOB_FAILURE_STATES:
                errors_str = self._extract_job_errors(status) or f"Job fehlgeschlagen (state={state})"
                emps.write({"datev_job_state": "failed", "datev_job_error": errors_str})
                continue
            if state not in _JOB_SUCCESS_STATES:
                _logger.info("DATEV hr:exchange job %s still pending (state=%r)", job_id, state)
                continue

            phase = emps[0].datev_job_phase
            if phase == "fetch":
                self._continue_after_fetch(service, client_id, job_id, emps)
            else:
                self._finalize_push(service, client_id, job_id, emps, status)
        return polled

    def _continue_after_fetch(self, service, client_id, job_id, emps):
        """Fetch job finished: read the employee list, decide create vs update
        per employee, then start the actual push (bulk POST / per-employee PUT)."""
        try:
            result = service.hr_exchange_job_result(client_id, job_id, "employees")
        except Exception as exc:
            emps.write({
                "datev_job_state": "failed",
                "datev_job_error": "Fetch-Ergebnis nicht abrufbar: %s" % str(exc)[:500],
            })
            return
        entries = result.get("employees", result) if isinstance(result, dict) else result
        existing_numbers = set()
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("personnel_number") is not None:
                existing_numbers.add(str(entry["personnel_number"]))

        reference_date = fields.Date.today().strftime("%Y-%m")
        to_create = self.browse()
        create_payloads = []
        for emp in emps:
            try:
                payload = emp._build_hr_exchange_payload()
            except Exception as exc:
                emp.write({
                    "datev_job_state": "failed",
                    "datev_job_error": str(exc)[:1000],
                })
                continue
            exists = str(int(emp.datev_personnel_number or "0")) in existing_numbers
            if exists:
                # Existence derived from the fetch result — not from a local flag.
                try:
                    job = service.hr_exchange_put_employee(
                        client_id, emp.datev_personnel_number, payload, reference_date,
                    )
                except Exception as exc:
                    emp.write({"datev_job_state": "failed", "datev_job_error": str(exc)[:1000]})
                    continue
                emp.write(self._push_job_vals(job))
            else:
                to_create |= emp
                create_payloads.append(payload)

        if to_create:
            try:
                job = service.hr_exchange_post_employees(client_id, create_payloads, reference_date)
            except Exception as exc:
                to_create.write({"datev_job_state": "failed", "datev_job_error": str(exc)[:1000]})
                return
            to_create.write(self._push_job_vals(job))

    @staticmethod
    def _push_job_vals(job):
        return {
            "datev_job_id": job.get("id"),
            "datev_job_phase": "push",
            "datev_job_state": "pending",
            "datev_job_error": False,
            "datev_job_created_at": fields.Datetime.now(),
            "datev_job_last_poll": False,
        }

    def _finalize_push(self, service, client_id, job_id, emps, status):
        """Push job reports success: fetch the result document (MUST) — it can
        still contain errors[] and carries the persisted personnel_number."""
        result = {}
        try:
            result = service.hr_exchange_job_result(client_id, job_id, "employees")
        except Exception as exc:
            _logger.warning("DATEV hr:exchange result fetch failed (%s): %s", job_id, exc)

        errors_str = self._extract_job_errors(status)
        if not errors_str and isinstance(result, dict):
            errors_str = self._extract_job_errors(result)

        if errors_str:
            # Success state but errors in the result → treat as failed;
            # datev_sync_created stays untouched: the next cycle re-derives
            # existence from a fresh fetch.
            emps.write({"datev_job_state": "failed", "datev_job_error": errors_str})
            _logger.error("DATEV hr:exchange job %s finished WITH errors: %s", job_id, errors_str)
            return

        entries = result.get("employees") if isinstance(result, dict) else None
        by_number = {}
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("personnel_number") is not None:
                by_number[str(entry["personnel_number"])] = entry

        now = fields.Datetime.now()
        for emp in emps:
            vals = {
                "datev_job_state": "succeeded",
                "datev_job_error": False,
                "datev_sync_created": True,
                "datev_last_sync": now,
                "datev_sync_error": False,
            }
            # Persist the personnel number DATEV reports back (it may have been
            # auto-assigned or normalized).
            current = str(int(emp.datev_personnel_number or "0"))
            if by_number and current not in by_number and len(emps) == 1 and len(by_number) == 1:
                vals["datev_personnel_number"] = next(iter(by_number))
            emp.write(vals)
        _logger.info("DATEV hr:exchange job %s verified successfully (%d employee(s)).", job_id, len(emps))
