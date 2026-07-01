import logging
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DATEV_AUTH_URL_PROD = "https://login.datev.de/openid/authorize"
DATEV_AUTH_URL_SANDBOX = "https://login.sandbox.datev.de/openid/authorize"
DATEV_TOKEN_URL_PROD = "https://login.datev.de/openid/token"
DATEV_TOKEN_URL_SANDBOX = "https://login.sandbox.datev.de/openid/token"


class DatevToken(models.Model):
    _name = "datev.token"
    _description = "DATEV OAuth2 Token"
    _rec_name = "company_id"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        ondelete="cascade",
        default=lambda self: self.env.company,
    )
    access_token = fields.Char(string="Access Token", copy=False)
    refresh_token = fields.Char(string="Refresh Token", copy=False)
    token_expiry = fields.Datetime(string="Token Expires At", copy=False)
    scope = fields.Char(string="Granted Scopes")
    state = fields.Selection(
        [("disconnected", "Disconnected"), ("connected", "Connected")],
        default="disconnected",
        readonly=True,
    )

    _sql_constraints = [
        ("unique_company", "UNIQUE(company_id)", "Only one DATEV token per company."),
    ]

    @api.model
    def _get_or_create(self, company_id=None):
        company_id = company_id or self.env.company.id
        token = self.search([("company_id", "=", company_id)], limit=1)
        if not token:
            token = self.create({"company_id": company_id})
        return token

    def is_access_token_valid(self):
        self.ensure_one()
        if not self.access_token or not self.token_expiry:
            return False
        return fields.Datetime.now() < self.token_expiry - timedelta(seconds=60)

    def refresh_access_token(self):
        self.ensure_one()
        if not self.refresh_token:
            raise UserError(_("No refresh token available. Please reconnect to DATEV."))
        config = self.env["res.config.settings"]._get_datev_config(self.company_id)
        from ..services.datev_api import DatevApiService

        service = DatevApiService(self.env, config)
        token_data = service.exchange_refresh_token(self.refresh_token)
        self._store_token_data(token_data)

    def _store_token_data(self, token_data):
        self.ensure_one()
        expires_in = token_data.get("expires_in", 3600)
        self.write(
            {
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token", self.refresh_token),
                "token_expiry": datetime.utcnow() + timedelta(seconds=expires_in),
                "scope": token_data.get("scope", ""),
                "state": "connected",
            }
        )

    def get_valid_access_token(self):
        self.ensure_one()
        if not self.is_access_token_valid():
            self.refresh_access_token()
        return self.access_token

    def action_disconnect(self):
        self.ensure_one()
        self.write(
            {
                "access_token": False,
                "refresh_token": False,
                "token_expiry": False,
                "scope": False,
                "state": "disconnected",
            }
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DATEV"),
                "message": _("Disconnected from DATEV Cloud."),
                "type": "warning",
            },
        }
