from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = "res.company"

    datev_target_system = fields.Selection(
        [("lodas", "LODAS"), ("lug", "Lohn und Gehalt")],
        string="DATEV Lohn-Abrechnungssystem",
        help="Abrechnungssystem des Mandanten. Steuert den Target-System-Header "
             "der Payroll-API. Pflicht, bevor Lohndaten übertragen werden.",
    )

    def datev_require_target_system(self):
        """Return the target system, raising if it is not configured."""
        self.ensure_one()
        if not self.datev_target_system:
            raise UserError(_(
                "DATEV: Bitte zuerst das Lohn-Abrechnungssystem (LODAS/LuG) für Firma "
                "'%s' in den Einstellungen (DATEV Cloud) festlegen."
            ) % self.name)
        return self.datev_target_system
