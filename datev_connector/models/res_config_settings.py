import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Per-company DATEV settings (stored on res.company).
    datev_client_id = fields.Char(
        related="company_id.datev_client_id", readonly=False,
    )
    datev_client_secret = fields.Char(
        related="company_id.datev_client_secret", readonly=False,
    )
    datev_sandbox_mode = fields.Boolean(
        related="company_id.datev_sandbox_mode", readonly=False,
    )
    datev_consultant_number = fields.Char(
        related="company_id.datev_consultant_number", readonly=False,
    )
    datev_client_number = fields.Char(
        related="company_id.datev_client_number", readonly=False,
    )
    datev_account_number_length = fields.Selection(
        related="company_id.datev_account_number_length", readonly=False,
    )
    datev_last_error = fields.Char(
        related="company_id.datev_last_error", readonly=True,
    )
    datev_service_accounting = fields.Boolean(
        related="company_id.datev_service_accounting", readonly=False,
    )
    datev_service_hr = fields.Boolean(
        related="company_id.datev_service_hr", readonly=False,
    )
    datev_connection_state = fields.Selection(
        [("disconnected", "Disconnected"), ("connected", "Connected")],
        string="Connection Status",
        compute="_compute_datev_connection_state",
    )

    @api.depends("company_id", "datev_client_id")
    def _compute_datev_connection_state(self):
        for rec in self:
            token = self.env["datev.token"].search(
                [("company_id", "=", rec.company_id.id)], limit=1
            )
            rec.datev_connection_state = token.state if token else "disconnected"

    @api.model
    def _get_datev_config(self, company=None):
        company = company or self.env.company
        return {
            "client_id": company.datev_client_id or "",
            "client_secret": company.datev_client_secret or "",
            "sandbox": bool(company.datev_sandbox_mode),
            "company_id": company.id,
        }

    def action_datev_connect(self):
        self.ensure_one()
        config = self._get_datev_config(self.company_id)
        if not config["client_id"] or not config["client_secret"]:
            raise UserError(_("Please enter your DATEV Client ID and Client Secret first."))
        # Clear any previous error at the start of a fresh connection attempt.
        self.company_id.sudo().datev_last_error = False

        from ..services.datev_api import DatevApiService

        service = DatevApiService(self.env, config)
        if service.get_scope() == "openid profile":
            raise UserError(_(
                "Bitte aktivieren Sie zuerst mindestens einen DATEV Datenservice "
                "(z. B. DATEV Buchungsdatenservice) in den Einstellungen. "
                "Es werden nur die Scopes angefragt, die Sie tatsächlich nutzen."
            ))
        auth_url = service.get_authorization_url()
        return {
            "type": "ir.actions.act_url",
            "url": auth_url,
            "target": "self",
        }

    def action_datev_disconnect(self):
        self.ensure_one()
        token = self.env["datev.token"].search(
            [("company_id", "=", self.company_id.id)], limit=1
        )
        if token:
            token.action_disconnect()

    def action_datev_fetch_clients(self):
        """Fetch available DATEV clients using the authenticated user token."""
        self.ensure_one()
        config = self._get_datev_config(self.company_id)

        from ..services.datev_api import DatevApiService

        service = DatevApiService(self.env, config)
        items = service.accounting_clients_list()
        if not items:
            raise UserError(_("No DATEV clients found. Please check your API product subscription."))

        def _fmt_client(c):
            services = ", ".join(s.get("name", "") for s in c.get("services", [])) or "–"
            return (
                "  {name}  |  Beraternummer: {berater}  |  Mandantennummer: {mandant}"
                "  |  Services: {services}"
            ).format(
                name=c.get("name", ""),
                berater=c.get("consultant_number", ""),
                mandant=c.get("client_number", ""),
                services=services,
            )

        client_list = "\n".join(_fmt_client(c) for c in items)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Available DATEV Clients"),
                "message": _(
                    "Enter Beraternummer and Mandantennummer in the fields above:\n%s"
                ) % client_list,
                "type": "info",
                "sticky": True,
            },
        }
