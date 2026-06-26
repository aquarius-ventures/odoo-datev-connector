from odoo import api, fields, models


class DatevEmployeeSyncWizard(models.TransientModel):
    _name = "datev.employee.sync.wizard"
    _description = "DATEV Cloud – Mitarbeiter Einstellungen"

    action = fields.Selection(
        [
            ("enable", "Synchronisation aktivieren"),
            ("disable", "Synchronisation deaktivieren"),
            ("transfer", "Jetzt übertragen (& Synchronisation aktivieren)"),
        ],
        string="Aktion",
        default="transfer",
        required=True,
    )
    employee_ids = fields.Many2many(
        "hr.employee",
        string="Ausgewählte Mitarbeiter",
        default=lambda self: self.env.context.get("active_ids", []),
    )
    missing_fields_html = fields.Html(
        string="Fehlende Pflichtfelder",
        compute="_compute_missing_fields_html",
        sanitize=False,
    )
    has_missing = fields.Boolean(compute="_compute_missing_fields_html")

    @api.depends("employee_ids", "action")
    def _compute_missing_fields_html(self):
        for rec in self:
            if rec.action == "disable":
                rec.missing_fields_html = False
                rec.has_missing = False
                continue

            issues = [
                (emp.name, emp.datev_get_missing_required_fields())
                for emp in rec.employee_ids
                if emp.datev_get_missing_required_fields()
            ]

            if not issues:
                rec.missing_fields_html = False
                rec.has_missing = False
                continue

            rows = "".join(
                f"<tr>"
                f"<td style='padding:4px 8px;font-weight:600'>{name}</td>"
                f"<td style='padding:4px 8px;color:#6c757d'>{', '.join(missing)}</td>"
                f"</tr>"
                for name, missing in issues
            )
            rec.missing_fields_html = (
                "<table style='border-collapse:collapse;width:100%'>"
                "<thead><tr style='border-bottom:1px solid #dee2e6'>"
                "<th style='padding:4px 8px;text-align:left'>Mitarbeiter</th>"
                "<th style='padding:4px 8px;text-align:left'>Fehlende Pflichtfelder</th>"
                "</tr></thead>"
                f"<tbody>{rows}</tbody>"
                "</table>"
            )
            rec.has_missing = True

    def action_execute(self):
        self.ensure_one()
        if self.action == "disable":
            self.employee_ids.write({"datev_sync_enabled": False})
        elif self.action == "enable":
            self.employee_ids.write({"datev_sync_enabled": True})
        elif self.action == "transfer":
            self.employee_ids.write({"datev_sync_enabled": True})
            self.employee_ids.with_context(
                _datev_sync_in_progress=False
            )._action_datev_sync()
        return {"type": "ir.actions.act_window_close"}
