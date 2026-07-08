import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# DATEV requires >= 14 days of technical HTTP logs; we keep 30 to be safe.
_LOG_RETENTION_DAYS = 30


class DatevApiLog(models.Model):
    """Technical HTTP log for all communication with the DATEV API gateway.

    Mandated by the DATEV interface requirements: chronological review of all
    HTTP requests, kept for at least 14 days, request headers WITHOUT the
    Authorization header, response headers at least X-Global-Transaction-ID
    and V-Cap-Request-ID, response body only for errors or status queries.
    Shown live at the DATEV release meeting.
    """

    _name = "datev.api.log"
    _description = "DATEV API HTTP Log"
    _order = "request_ts desc, id desc"

    request_ts = fields.Datetime(string="Request Timestamp", required=True, index=True)
    method = fields.Char(string="Method", required=True)
    url = fields.Char(string="URL (incl. query)", required=True)
    request_headers = fields.Text(
        string="Request Headers",
        help="Authorization and X-DATEV-Client-Secret are redacted.",
    )
    response_ts = fields.Datetime(string="Response Timestamp")
    status_code = fields.Integer(string="HTTP Status")
    x_global_transaction_id = fields.Char(string="X-Global-Transaction-ID")
    v_cap_request_id = fields.Char(string="V-Cap-Request-ID")
    response_body = fields.Text(
        string="Response Body",
        help="Only stored for errors (HTTP >= 400) and status queries.",
    )
    error = fields.Char(string="Transport Error")
    company_id = fields.Many2one("res.company")

    @api.model
    def _cron_vacuum(self):
        cutoff = fields.Datetime.now() - timedelta(days=_LOG_RETENTION_DAYS)
        old = self.search([("request_ts", "<", cutoff)])
        if old:
            _logger.info("DATEV API log vacuum: deleting %d entries older than %d days.", len(old), _LOG_RETENTION_DAYS)
            old.unlink()
