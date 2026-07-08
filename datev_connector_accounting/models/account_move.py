import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    datev_exported = fields.Boolean(
        string="Exported to DATEV",
        default=False,
        copy=False,
        help="Set after a successful EXTF export to DATEV Cloud. Reset "
        "automatically when the DATEV import job fails, so the entry is "
        "picked up by the next export again.",
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
    datev_job_created_at = fields.Datetime(
        string="DATEV Job Created At",
        copy=False,
        readonly=True,
    )
    datev_job_last_poll = fields.Datetime(
        string="DATEV Job Last Poll",
        copy=False,
        readonly=True,
    )
    datev_job_next_poll = fields.Datetime(
        string="DATEV Job Next Poll",
        copy=False,
        readonly=True,
        help="Earliest allowed poll time, taken from the Retry-After header " "of the upload response.",
    )

    # Poll cadence: no permanent polling (DATEV DONT). First poll after
    # Retry-After (or >= 60 s), max one poll per minute per job, give up after
    # 24 h (DATEV batch processing can take a while — unlike hr:exchange there
    # is no documented 15-min limit for EXTF).
    _POLL_MIN_AGE = timedelta(seconds=60)
    _POLL_INTERVAL = timedelta(seconds=60)
    _POLL_TIMEOUT = timedelta(hours=24)

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
        polled = pending._poll_datev_jobs()
        if not polled:
            raise UserError(
                _("DATEV erlaubt höchstens eine Statusabfrage pro Minute je Job. " "Bitte in Kürze erneut versuchen.")
            )
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
        pending = self.search(
            [
                ("datev_job_url", "!=", False),
                ("datev_job_state", "=", "pending"),
            ]
        )
        if pending:
            pending._poll_datev_jobs()

    def _poll_datev_jobs(self):
        """Poll pending EXTF jobs, grouped per company and job URL, honoring
        the poll cadence. Returns the number of jobs actually polled."""
        from odoo.addons.datev_connector.services.datev_api import DatevApiService

        now = fields.Datetime.now()
        polled = 0
        # Group by company first (multi-company: each company has its own
        # token/config), then by job URL (one upload covers many moves).
        for company in self.mapped("company_id"):
            moves = self.filtered(lambda m: m.company_id == company)
            token = self.env["datev.token"].sudo().search([("company_id", "=", company.id)], limit=1)
            if not token or token.state != "connected":
                # No connection (e.g. RT expired): don't generate error spam —
                # the user is asked to reconnect via the settings status.
                _logger.info("DATEV EXTF poll skipped for %s: not connected.", company.name)
                continue
            try:
                config = self.env["res.config.settings"]._get_datev_config(company)
            except UserError:
                # e.g. DATEV switched to 'Deaktiviert' while jobs are pending
                continue
            service = DatevApiService(self.env, config)

            for job_url in set(moves.mapped("datev_job_url")):
                job_moves = moves.filtered(lambda m: m.datev_job_url == job_url)
                created_dates = [d for d in job_moves.mapped("datev_job_created_at") if d]
                poll_dates = [d for d in job_moves.mapped("datev_job_last_poll") if d]
                next_polls = [d for d in job_moves.mapped("datev_job_next_poll") if d]
                created_at = min(created_dates) if created_dates else False
                last_poll = max(poll_dates) if poll_dates else False
                next_poll = max(next_polls) if next_polls else False

                if next_poll and now < next_poll:
                    continue
                if not next_poll and created_at and now - created_at < self._POLL_MIN_AGE:
                    continue
                if last_poll and now - last_poll < self._POLL_INTERVAL:
                    continue
                if created_at and now - created_at > self._POLL_TIMEOUT:
                    job_moves.write(
                        {
                            "datev_job_state": "failed",
                            "datev_job_error": "Zeitüberschreitung (24 h) — Status unbekannt, "
                            "bitte manuell in DATEV prüfen.",
                            "datev_exported": False,
                        }
                    )
                    _logger.error("DATEV EXTF job %s timed out after 24 h.", job_url)
                    continue

                job_moves.write({"datev_job_last_poll": now})
                polled += 1
                result = service.extf_job_status(job_url)
                outcome = result.get("_result", "pending")
                if outcome == "pending":
                    continue
                errors = result.get("_errors", [])
                vals = {
                    "datev_job_state": outcome if outcome in ("succeeded", "failed") else "pending",
                    "datev_job_error": "\n".join(errors) if errors else False,
                }
                if vals["datev_job_state"] == "failed":
                    # P1.7: a failed upload must not stay flagged as exported —
                    # the standard export flow has to find these moves again.
                    vals["datev_exported"] = False
                job_moves.write(vals)
        return polled
