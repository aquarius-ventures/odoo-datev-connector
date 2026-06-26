import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

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
}


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # ── Sync status ─────────────────────────────────────────────────────────
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

    # ── Sozialversicherung ──────────────────────────────────────────────────
    datev_health_insurance_name = fields.Char(
        string="Krankenkasse",
        groups="hr.group_hr_user",
    )
    datev_health_insurance_type = fields.Selection(
        [("gkv", "GKV – Gesetzlich"), ("pkv", "PKV – Privat")],
        string="Versicherungsart",
        groups="hr.group_hr_user",
    )
    datev_child_allowance = fields.Float(
        string="Kinderfreibetrag",
        digits=(4, 1),
        groups="hr.group_hr_user",
        help="z. B. 0.5 je Kind bei gemeinsamer Veranlagung.",
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

    def _push_employee_to_datev(self, emp):
        """Build and submit the LODAS Personalstammdaten payload for one employee.

        DATEV LODAS REST API endpoint and exact payload format to be confirmed
        once the API product subscription is active in the developer portal.
        """
        # TODO: replace with actual DATEV LODAS API call once endpoint is known.
        # Expected flow:
        #   1. Generate LODAS Stammsatz content (reuse LodasGenerator)
        #   2. POST to https://lodas.api.datev.de/... (sandbox / prod)
        #   3. Poll or handle synchronous response
        _logger.info(
            "DATEV LODAS push (stub): %s | Personalnr=%s | Steuerklasse=%s | SV=%s",
            emp.name,
            emp.datev_personnel_number,
            emp.datev_tax_class,
            emp.ssnid,
        )
