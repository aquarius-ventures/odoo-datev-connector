from odoo import _, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    def action_datev_check_client_hr(self):
        """Authorization check for the Lohnaustauschdatenservice (MUST):
        GET hr-exchange /clients/{client-id} confirms token access to the
        payroll client."""
        self.ensure_one()
        company = self.company_id
        client_id = company.datev_get_client_id()

        from odoo.addons.datev_connector.services.datev_api import DatevApiService

        service = DatevApiService(self.env, self._get_datev_config(company))
        try:
            client = service.hr_exchange_get_client(client_id)
        except UserError as exc:
            raise UserError(_(
                "DATEV Lohnaustauschdatenservice: Berechtigungsprüfung für "
                "Mandant %s fehlgeschlagen.\n%s"
            ) % (client_id, exc)) from exc
        name = client.get("name") or client.get("client_name") or client_id
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DATEV Mandantenprüfung (HR)"),
                "message": _("Zugriff auf Mandant %s (hr:exchange) bestätigt.") % name,
                "type": "success",
            },
        }
