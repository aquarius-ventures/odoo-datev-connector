import logging
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
    refresh_token_expiry = fields.Datetime(
        string="Refresh Token Expires At",
        copy=False,
        readonly=True,
        help="DATEV short-term refresh tokens live 11 hours from the first "
             "access-token issuance; a token refresh does NOT extend this.",
    )
    issued_by_name = fields.Char(
        string="Issued By",
        copy=False,
        readonly=True,
        help="Full name of the DATEV user who authorized this connection "
             "(from the OIDC userinfo endpoint).",
    )
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
        """Redeem the refresh token — serialized across workers.

        DATEV refresh tokens are single-use: redeeming one twice invalidates
        the whole session. Cron jobs and users can hit this concurrently, so
        the refresh runs in its own transaction under a row lock and commits
        immediately — a later rollback of the business transaction must never
        throw away an already-redeemed RT. Returns the valid access token.
        """
        self.ensure_one()
        from ..services.datev_api import DatevApiService

        with self.pool.cursor() as cr:
            cr.execute("SELECT id FROM datev_token WHERE id = %s FOR UPDATE", (self.id,))
            env = api.Environment(cr, self.env.uid, self.env.context)
            token = env["datev.token"].browse(self.id)
            # Another worker may have refreshed while we waited for the lock.
            if token.is_access_token_valid():
                return token.access_token
            if not token.refresh_token:
                raise UserError(_("No refresh token available. Please reconnect to DATEV."))
            config = env["res.config.settings"]._get_datev_config(token.company_id)
            service = DatevApiService(env, config)
            try:
                token_data = service.exchange_refresh_token(token.refresh_token)
            except Exception as exc:
                # One failed attempt disconnects the token — no retry spam
                # against an invalid RT (10% error-rate requirement).
                token.write({
                    "access_token": False,
                    "refresh_token": False,
                    "token_expiry": False,
                    "state": "disconnected",
                })
                token.company_id.sudo().datev_last_error = (
                    "Token-Refresh fehlgeschlagen — bitte neu mit DATEV verbinden. (%s)"
                    % str(exc)[:200]
                )
                # Persist the disconnect before raising — the context manager
                # would otherwise roll it back together with the exception.
                cr.commit()
                self.invalidate_recordset()
                raise UserError(_(
                    "DATEV: Die Verbindung ist abgelaufen oder ungültig. "
                    "Bitte neu mit DATEV verbinden."
                )) from exc
            token._store_token_data(token_data)
            access_token = token.access_token
        # The inner transaction committed; drop stale values from this env's cache.
        self.invalidate_recordset()
        return access_token

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

    def _update_issuer_info(self, service, token_data):
        """After a fresh connect: compute the RT expiry (first AT issuance
        + 11 h, never extended on refresh) and fetch the issuer's full name."""
        self.ensure_one()
        vals = {"refresh_token_expiry": datetime.utcnow() + timedelta(hours=11)}
        info = service.get_userinfo(token_data.get("access_token") or self.access_token)
        name = " ".join(
            part for part in (info.get("given_name"), info.get("family_name")) if part
        ) or info.get("name")
        vals["issued_by_name"] = name or False
        self.write(vals)

    def get_valid_access_token(self):
        self.ensure_one()
        if self.state != "connected":
            raise UserError(_("DATEV: Not connected. Please authenticate first."))
        if self.is_access_token_valid():
            return self.access_token
        return self.refresh_access_token()

    def action_disconnect(self):
        """Disconnect = revoke both tokens at DATEV (MUST), then clear locally.

        Revocation failures are logged; the local disconnect always proceeds.
        """
        self.ensure_one()
        if self.access_token or self.refresh_token:
            from ..services.datev_api import DatevApiService

            try:
                config = self.env["res.config.settings"]._get_datev_config(self.company_id)
                service = DatevApiService(self.env, config)
                if self.access_token:
                    service.revoke_token(self.access_token, "access_token")
                if self.refresh_token:
                    service.revoke_token(self.refresh_token, "refresh_token")
            except Exception as exc:
                _logger.warning("DATEV disconnect: revoke skipped/failed: %s", exc)
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
                "message": _("Disconnected from DATEV Cloud (tokens revoked)."),
                "type": "warning",
            },
        }
