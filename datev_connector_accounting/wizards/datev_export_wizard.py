import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DatevExportWizard(models.TransientModel):
    _name = "datev.export.wizard"
    _description = "DATEV Accounting Export"

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
    journal_ids = fields.Many2many(
        "account.journal",
        string="Journals",
        help="Leave empty to export all journals.",
    )
    move_ids = fields.Many2many(
        "account.move",
        string="Journal Entries",
        help="Pre-selected entries (overrides date range when set).",
    )
    include_exported = fields.Boolean(
        string="Include already exported",
        default=False,
    )
    export_mode = fields.Selection(
        [("download", "Download CSV"), ("upload", "Upload to DATEV Cloud")],
        default="upload",
        required=True,
        string="Export Mode",
    )

    @api.onchange("date_from", "date_to")
    def _onchange_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            return {"warning": {"title": _("Warning"), "message": _("'From' must be before 'To'.")}}

    def _get_moves(self):
        if self.move_ids:
            return self.move_ids.filtered(lambda m: m.state == "posted")
        domain = [
            ("state", "=", "posted"),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("company_id", "=", self.env.company.id),
        ]
        if self.journal_ids:
            domain.append(("journal_id", "in", self.journal_ids.ids))
        if not self.include_exported:
            domain.append(("datev_exported", "=", False))
        return self.env["account.move"].search(domain)

    def action_export(self):
        self.ensure_one()
        moves = self._get_moves()
        if not moves:
            raise UserError(_("No journal entries found for the selected criteria."))

        from ..services.extf_generator import ExtfGenerator

        generator = ExtfGenerator(self.env, self.env.company, self.date_from, self.date_to)
        csv_bytes = generator.generate(moves)

        if self.export_mode == "download":
            return self._action_download(csv_bytes)
        return self._action_upload(csv_bytes, moves)

    def _action_download(self, csv_bytes: bytes):
        attachment = self.env["ir.attachment"].create(
            {
                "name": f"EXTF_Buchungsstapel_{self.date_from}_{self.date_to}.csv",
                "datas": base64.b64encode(csv_bytes),
                "mimetype": "text/csv",
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def _action_upload(self, csv_bytes: bytes, moves):
        from odoo.addons.datev_connector.services.datev_api import DatevApiService

        config = self.env["res.config.settings"]._get_datev_config()
        service = DatevApiService(self.env, config)

        ICP = self.env["ir.config_parameter"].sudo()
        consultant_number = ICP.get_param("datev_connector.consultant_number", "")
        client_number = ICP.get_param("datev_connector.client_number", "")
        if not consultant_number or not client_number:
            raise UserError(
                _("Please configure Consultant Number and Client Number in Settings → DATEV Cloud.")
            )

        client_id = f"{consultant_number}-{client_number}"
        filename = f"EXTF_Buchungsstapel_{self.date_from.strftime('%Y%m%d')}_{self.date_to.strftime('%Y%m%d')}.csv"
        resp = service.extf_import(client_id, filename, csv_bytes)

        # 202 Accepted = async job queued successfully
        job_location = resp.headers.get("Location", "")
        now = fields.Datetime.now()
        moves.write({"datev_exported": True, "datev_export_date": now})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DATEV Export"),
                "message": _(
                    "%d journal entries submitted to DATEV (job: %s)."
                ) % (len(moves), job_location or "queued"),
                "type": "success",
            },
        }
