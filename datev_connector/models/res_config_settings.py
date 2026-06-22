import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    datev_client_id = fields.Char(
        string="DATEV Client ID",
        config_parameter="datev_connector.client_id",
    )
    datev_client_secret = fields.Char(
        string="DATEV Client Secret",
        config_parameter="datev_connector.client_secret",
    )
    datev_sandbox_mode = fields.Boolean(
        string="Sandbox Mode",
        config_parameter="datev_connector.sandbox_mode",
    )
    datev_consultant_number = fields.Char(
        string="Consultant Number",
        config_parameter="datev_connector.consultant_number",
    )
    datev_client_number = fields.Char(
        string="Client Number",
        config_parameter="datev_connector.client_number",
    )
    datev_connection_state = fields.Selection(
        [("disconnected", "Disconnected"), ("connected", "Connected")],
        string="Connection Status",
        compute="_compute_datev_connection_state",
    )

    @api.depends("datev_client_id")
    def _compute_datev_connection_state(self):
        for rec in self:
            token = self.env["datev.token"].search(
                [("company_id", "=", self.env.company.id)], limit=1
            )
            rec.datev_connection_state = token.state if token else "disconnected"

    @api.model
    def _get_datev_config(self):
        ICP = self.env["ir.config_parameter"].sudo()
        sandbox = ICP.get_param("datev_connector.sandbox_mode", "False") == "True"
        return {
            "client_id": ICP.get_param("datev_connector.client_id", ""),
            "client_secret": ICP.get_param("datev_connector.client_secret", ""),
            "sandbox": sandbox,
        }

    def action_datev_connect(self):
        self.ensure_one()
        config = self._get_datev_config()
        if not config["client_id"] or not config["client_secret"]:
            raise UserError(_("Please enter your DATEV Client ID and Client Secret first."))

        from ..services.datev_api import DatevApiService

        service = DatevApiService(self.env, config)
        auth_url = service.get_authorization_url()
        return {
            "type": "ir.actions.act_url",
            "url": auth_url,
            "target": "self",
        }

    def action_datev_disconnect(self):
        self.ensure_one()
        token = self.env["datev.token"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        if token:
            token.action_disconnect()

    def action_datev_fetch_clients(self):
        """Fetch available DATEV clients using Client Credentials (app credentials)."""
        self.ensure_one()
        config = self._get_datev_config()
        if not config["client_id"] or not config["client_secret"]:
            raise UserError(_("Please enter your DATEV Client ID and Client Secret first."))

        import requests

        env_key = "sandbox" if config.get("sandbox") else "prod"
        token_url = {
            "prod": "https://login.datev.de/openid/token",
            "sandbox": "https://login.datev.de/openidsandbox/token",
        }[env_key]
        clients_url = {
            "prod": "https://accounting-clients.api.datev.de/platform/v2/clients",
            "sandbox": "https://accounting-clients.api.datev.de/platform-sandbox/v2/clients",
        }[env_key]

        # Client Credentials Grant — no user interaction, uses app credentials directly
        token_resp = requests.post(
            token_url,
            data={"grant_type": "client_credentials", "scope": "datev:accounting:clients:read"},
            auth=(config["client_id"], config["client_secret"]),
            timeout=30,
        )
        if not token_resp.ok:
            raise UserError(_("DATEV token (client credentials) failed: %s") % token_resp.text)

        app_token = token_resp.json().get("access_token")
        if not app_token:
            raise UserError(_("No access token in DATEV response: %s") % token_resp.text)

        resp = requests.get(
            clients_url,
            headers={"Authorization": f"Bearer {app_token}", "Accept": "application/json"},
            timeout=30,
        )
        if not resp.ok:
            raise UserError(_("DATEV clients fetch failed: %s") % resp.text)

        data = resp.json()
        items = data if isinstance(data, list) else data.get("data", data.get("clients", []))
        if not items:
            raise UserError(_("No DATEV clients found. Please check your API product subscription."))

        client_list = "\n".join(
            f"  {c.get('id', c.get('clientId', ''))}  —  {c.get('name', c.get('clientName', ''))}"
            for c in items
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Available DATEV Clients"),
                "message": _("Copy the Client Number into the field below:\n%s") % client_list,
                "type": "info",
                "sticky": True,
            },
        }
