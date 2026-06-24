import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    datev_exported = fields.Boolean(
        string="Exported to DATEV",
        default=False,
        copy=False,
        help="Set after a successful EXTF export to DATEV Cloud.",
    )
    datev_export_date = fields.Datetime(
        string="DATEV Export Date",
        copy=False,
        readonly=True,
    )
    datev_job_url = fields.Char(
        string="DATEV Job URL",
        copy=False,
        readonly=True,
    )
    datev_job_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("succeeded", "Succeeded"),
            ("failed", "Failed"),
        ],
        string="DATEV Job Status",
        copy=False,
        readonly=True,
    )
    datev_job_error = fields.Text(
        string="DATEV Job Error",
        copy=False,
        readonly=True,
    )

    def action_datev_export_single(self):
        self.ensure_one()
        if self.state != "posted":
            raise UserError(_("Only posted journal entries can be exported to DATEV."))
        wizard = self.env["datev.export.wizard"].create({"move_ids": [(4, self.id)]})
        return wizard.action_export()

    def action_datev_refresh_job_status(self):
        """Manually refresh DATEV job status for selected moves."""
        pending = self.filtered(lambda m: m.datev_job_url and m.datev_job_state == "pending")
        if not pending:
            raise UserError(_("No pending DATEV jobs found for the selected entries."))
        self._poll_datev_jobs(pending)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DATEV Job Status"),
                "message": _("Job status refreshed."),
                "type": "info",
            },
        }

    @api.model
    def _cron_poll_datev_jobs(self):
        pending = self.search([
            ("datev_job_url", "!=", False),
            ("datev_job_state", "=", "pending"),
        ])
        if pending:
            self._poll_datev_jobs(pending)

    @api.model
    def _poll_datev_jobs(self, moves):
        config = self.env["res.config.settings"]._get_datev_config()
        from odoo.addons.datev_connector.services.datev_api import DatevApiService
        service = DatevApiService(self.env, config)

        seen_urls = {}
        for move in moves:
            url = move.datev_job_url
            if url not in seen_urls:
                seen_urls[url] = service.extf_job_status(url)

        for move in moves:
            result = seen_urls.get(move.datev_job_url, {})
            outcome = result.get("_result", "pending")
            if outcome == "pending":
                continue
            errors = result.get("_errors", [])
            move.write({
                "datev_job_state": outcome if outcome in ("succeeded", "failed") else "pending",
                "datev_job_error": "\n".join(errors) if errors else False,
            })
