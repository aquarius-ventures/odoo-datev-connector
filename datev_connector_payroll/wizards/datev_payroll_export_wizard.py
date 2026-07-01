from odoo import _, fields, models
from odoo.exceptions import UserError


class DatevPayrollExportWizard(models.TransientModel):
    _name = "datev.payroll.export.wizard"
    _description = "DATEV Payroll Export"

    date_from = fields.Date(
        string="From",
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string="To",
        required=True,
        default=fields.Date.today,
    )
    payslip_ids = fields.Many2many(
        "hr.payslip",
        string="Payslips",
        help="Pre-selected payslips (overrides date range when set).",
    )
    include_exported = fields.Boolean(
        string="Include already exported",
        default=False,
    )
    export_mode = fields.Selection(
        [("download", "Download File"), ("upload", "Upload to DATEV Cloud")],
        default="upload",
        required=True,
        string="Export Mode",
    )

    def _get_payslips(self):
        if self.payslip_ids:
            return self.payslip_ids
        domain = [
            ("state", "in", ["done", "paid"]),
            ("date_from", ">=", self.date_from),
            ("date_to", "<=", self.date_to),
        ]
        if not self.include_exported:
            domain.append(("datev_exported", "=", False))
        return self.env["hr.payslip"].search(domain)

    def action_export(self):
        self.ensure_one()
        payslips = self._get_payslips()
        if not payslips:
            raise UserError(_("No payslips found for the selected criteria."))

        from ..services.lodas_generator import LodasGenerator

        generator = LodasGenerator(self.env, self.env.company)
        file_bytes = generator.generate(payslips)

        if self.export_mode == "download":
            attachment = self.env["ir.attachment"].create(
                {
                    "name": f"DATEV_LODAS_{self.date_from}_{self.date_to}.txt",
                    "datas": file_bytes,
                    "mimetype": "text/plain",
                }
            )
            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{attachment.id}?download=true",
                "target": "self",
            }

        # Upload via DATEV Payroll API (endpoint to be confirmed with developer portal)
        from odoo.addons.datev_connector.services.datev_api import DatevApiService

        company = self.env.company
        config = self.env["res.config.settings"]._get_datev_config(company)
        service = DatevApiService(self.env, config)
        client_number = company.datev_client_number or ""
        if not client_number:
            raise UserError(
                _("Please configure the DATEV Client Number in Settings → DATEV Cloud.")
            )
        resp = service.post(
            f"/payroll/clients/{client_number}/lodas/import",
            data=file_bytes,
            headers={"Content-Type": "text/plain; charset=windows-1252"},
        )
        if resp.status_code in (200, 201, 202):
            now = fields.Datetime.now()
            payslips.write({"datev_exported": True, "datev_export_date": now})
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("DATEV Payroll Export"),
                    "message": _("%d payslips exported to DATEV.") % len(payslips),
                    "type": "success",
                },
            }
        raise UserError(_("DATEV payroll upload failed: %s") % resp.text)
