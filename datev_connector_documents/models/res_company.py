from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    datev_service_documents = fields.Boolean(
        string="DATEV Belegbilderservice",
        help="Überträgt Belegbilder (z. B. Rechnungs-PDFs) vor dem "
        "Buchungsstapel nach DATEV Unternehmen online und verknüpft sie "
        "über den Beleglink (BEDI-GUID). Fragt den Scope "
        "datev:accounting:documents an. Der Belegbilderservice muss beim "
        "Steuerberater/DATEV bestellt und aktiviert sein: "
        "http://go.datev.de/datenservices-einrichten",
    )

    def datev_get_additional_scopes(self):
        scopes = super().datev_get_additional_scopes()
        if self.datev_service_documents:
            scopes.append("datev:accounting:documents")
        return scopes
