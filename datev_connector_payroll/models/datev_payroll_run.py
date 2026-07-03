from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DatevPayrollRun(models.Model):
    """A payroll import/transfer batch for one company and reference month."""

    _name = "datev.payroll.run"
    _description = "DATEV Lohnlauf (Payroll Run)"
    _order = "reference_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    reference_date = fields.Char(
        string="Abrechnungsmonat", required=True, help="Format yyyy-MM, z. B. 2026-01."
    )
    target_system = fields.Selection(
        [("lodas", "LODAS"), ("lug", "Lohn und Gehalt")],
        string="Abrechnungssystem",
    )
    state = fields.Selection(
        [
            ("draft", "Entwurf"),
            ("imported", "Importiert"),
            ("validated", "Validiert"),
            ("sent", "Übertragen"),
            ("done", "Fertig"),
            ("error", "Fehler"),
        ],
        default="draft",
        required=True,
    )
    line_ids = fields.One2many("datev.payroll.line", "run_id", string="Zeilen")
    line_count = fields.Integer(compute="_compute_counts")
    error_count = fields.Integer(compute="_compute_counts")
    # P3 job tracking (placeholders until the transfer layer is built)
    job_id = fields.Char(readonly=True, copy=False)
    job_state = fields.Selection(
        [("pending", "Pending"), ("succeeded", "Succeeded"), ("failed", "Failed")],
        readonly=True, copy=False,
    )
    job_error = fields.Text(readonly=True, copy=False)

    @api.depends("reference_date", "company_id")
    def _compute_name(self):
        for rec in self:
            rec.name = "Lohnlauf %s / %s" % (rec.reference_date or "?", rec.company_id.name or "")

    @api.depends("line_ids", "line_ids.error")
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.error_count = len(rec.line_ids.filtered("error"))

    def action_validate(self):
        self.ensure_one()
        self.company_id.datev_require_target_system()
        self.line_ids._validate()
        if self.error_count:
            raise UserError(
                _("%d Zeile(n) haben Fehler. Bitte korrigieren, bevor du fortfährst.")
                % self.error_count
            )
        self.state = "validated"

    def action_transfer(self):
        self.ensure_one()
        # P3: real transfer to DATEV (month-records / gross-payments / hourly-wages).
        raise UserError(_(
            "Der Transfer an DATEV ist noch nicht aktiv (Phase P3). "
            "Er wird freigeschaltet, sobald ein Lohn-fähiger Mandant bereitsteht."
        ))

    def action_open_import(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "datev.payroll.import.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_run_id": self.id,
                "default_company_id": self.company_id.id,
            },
        }
