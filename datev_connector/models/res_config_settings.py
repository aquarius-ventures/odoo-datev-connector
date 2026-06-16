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
