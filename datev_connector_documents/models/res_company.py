from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    datev_service_documents = fields.Boolean(
        string="DATEV Belegbilderservice",
        help="Überträgt Belegbilder (z. B. Rechnungs-PDFs) vor dem "
        "Buchungsstapel nach DATEV Unternehmen online und verknüpft sie "
        "über den Beleglink (BEDI-GUID). Fragt die Scopes "
        "accounting:documents und accounting:clients:read an. Der "
        "Belegbilderservice muss beim Steuerberater/DATEV bestellt und "
        "aktiviert sein: http://go.datev.de/datenservices-einrichten",
    )

    def datev_get_additional_scopes(self):
        scopes = super().datev_get_additional_scopes()
        if self.datev_service_documents:
            # Wire names per the accounting-documents OpenAPI securitySchemes:
            # unlike extf-files/accounting-clients these have NO 'datev:'
            # prefix. accounting:clients:read is required by the API's own
            # GET /clients/{client-id} authorization check.
            scopes += ["accounting:documents", "accounting:clients:read"]
        return scopes
