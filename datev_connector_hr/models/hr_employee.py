import json
import logging
import os

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
    datev_job_id = fields.Char(
        string="DATEV Job-ID",
        readonly=True,
        copy=False,
        groups="hr.group_hr_user",
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

    # ── Sync logic ──────────────────────────────────────────────────────────

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("_datev_sync_in_progress") and (
            _DATEV_SYNC_FIELDS & set(vals.keys())
        ):
            to_sync = self.filtered("datev_sync_enabled")
            if to_sync:
                to_sync.with_context(_datev_sync_in_progress=True)._action_datev_sync()
        return result

    def datev_get_missing_required_fields(self):
        """Return list of human-readable labels for unfilled required fields."""
        self.ensure_one()
        return [
            label
            for fname, label in _DATEV_REQUIRED_FIELDS.items()
            if not getattr(self, fname, False)
        ]

    def _action_datev_sync(self):
        """Push this employee's master data to DATEV Cloud (LODAS)."""
        for emp in self:
            missing = emp.datev_get_missing_required_fields()
            if missing:
                error = "Fehlende Pflichtfelder: " + ", ".join(missing)
                emp.write({"datev_sync_error": error, "datev_last_sync": False})
                _logger.warning(
                    "DATEV sync skipped for employee %s (%d): %s",
                    emp.name, emp.id, error,
                )
                continue

            try:
                self._push_employee_to_datev(emp)
                emp.write({
                    "datev_last_sync": fields.Datetime.now(),
                    "datev_sync_error": False,
                })
                _logger.info(
                    "DATEV sync succeeded for employee %s (Personalnr. %s)",
                    emp.name, emp.datev_personnel_number,
                )
            except Exception as exc:
                emp.write({"datev_sync_error": str(exc)})
                _logger.error(
                    "DATEV sync failed for employee %s: %s", emp.name, exc
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

        if self.datev_cost_center:
            payload["activity"] = {"individual_cost_center_id": self.datev_cost_center[:13]}

        return payload

    def _push_employee_to_datev(self, emp):
        """Submit employee master data to the DATEV hr:exchange API (async job)."""
        ICP = self.env["ir.config_parameter"].sudo()
        consultant = ICP.get_param("datev_connector.consultant_number", "")
        client_nr = ICP.get_param("datev_connector.client_number", "")
        if not consultant or not client_nr:
            raise UserError(
                "DATEV: Bitte Berater- und Mandantennummer in den Einstellungen hinterlegen."
            )

        datev_client_id = f"{consultant}-{client_nr}"
        reference_date = fields.Date.today().strftime("%Y-%m")

        config = self.env["res.config.settings"]._get_datev_config()

        from odoo.addons.datev_connector.services.datev_api import DatevApiService

        service = DatevApiService(self.env, config)
        payload = emp._build_hr_exchange_payload()

        if emp.datev_sync_created:
            job = service.hr_exchange_put_employee(
                datev_client_id,
                emp.datev_personnel_number,
                payload,
                reference_date,
            )
        else:
            job = service.hr_exchange_post_employees(
                datev_client_id,
                [payload],
                reference_date,
            )
            emp.write({"datev_sync_created": True})

        job_id = job.get("id")
        _logger.info(
            "DATEV hr:exchange job accepted: emp=%s (Personalnr. %s) | job_id=%s | state=%s",
            emp.name, emp.datev_personnel_number, job_id, job.get("state"),
        )
        emp.write({"datev_job_id": job_id, "datev_job_state": "pending", "datev_job_error": False})

    def action_datev_refresh_job_status(self):
        pending = self.filtered(lambda e: e.datev_job_id and e.datev_job_state == "pending")
        if not pending:
            raise UserError("Keine offenen DATEV-Jobs für die ausgewählten Mitarbeiter.")
        pending._poll_datev_hr_jobs()
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

    def _poll_datev_hr_jobs(self):
        ICP = self.env["ir.config_parameter"].sudo()
        consultant = ICP.get_param("datev_connector.consultant_number", "")
        client_nr = ICP.get_param("datev_connector.client_number", "")
        datev_client_id = f"{consultant}-{client_nr}"
        config = self.env["res.config.settings"]._get_datev_config()
        from odoo.addons.datev_connector.services.datev_api import DatevApiService
        service = DatevApiService(self.env, config)

        for emp in self:
            try:
                result = service.hr_exchange_job_status(datev_client_id, emp.datev_job_id)
            except Exception as exc:
                _logger.warning("DATEV hr:exchange job poll failed for %s: %s", emp.name, exc)
                continue

            # Log the full raw response so the real state/error shapes can be verified.
            _logger.info(
                "DATEV hr:exchange job %s raw status (emp=%s): %s",
                emp.datev_job_id, emp.name, result,
            )

            state = (result.get("state") or result.get("status") or "").lower()
            errors_str = self._extract_job_errors(result)

            if state in _JOB_FAILURE_STATES or (state in _JOB_SUCCESS_STATES and errors_str):
                outcome = "failed"
            elif state in _JOB_SUCCESS_STATES:
                outcome = "succeeded"
            else:
                # Unknown or still-running state → keep pending; surfaced in log above.
                _logger.info(
                    "DATEV hr:exchange job %s still pending (state=%r) for %s",
                    emp.datev_job_id, state, emp.name,
                )
                continue

            emp.write({"datev_job_state": outcome, "datev_job_error": errors_str})
            _logger.info(
                "DATEV hr:exchange job %s → %s: emp=%s", emp.datev_job_id, outcome, emp.name
            )
