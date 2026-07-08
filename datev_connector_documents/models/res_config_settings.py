from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    datev_service_documents = fields.Boolean(
        related="company_id.datev_service_documents", readonly=False,
    )

    def action_datev_check_client_documents(self):
        """Authorization check for the Belegbilderservice (MUST):
        GET accounting-documents /clients/{client-id}."""
        self.ensure_one()
        company = self.company_id
        client_id = company.datev_get_client_id()

        from odoo.addons.datev_connector.services.datev_api import DatevApiService

        service = DatevApiService(self.env, self._get_datev_config(company))
        client = service.documents_get_client(client_id)
        name = client.get("name") or client_id
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DATEV Mandantenprüfung (Belegbilder)"),
                "message": _("Zugriff auf Mandant %s (Belegbilderservice) bestätigt.") % name,
                "type": "success",
            },
        }
