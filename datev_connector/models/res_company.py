from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = "res.company"

    # DATEV connection settings — per company, so one Odoo instance can talk to
    # several DATEV clients (Mandanten), one per company.
    datev_client_id = fields.Char(string="DATEV Client ID")
    datev_client_secret = fields.Char(string="DATEV Client Secret")
    datev_sandbox_mode = fields.Boolean(string="DATEV Sandbox Mode")
    datev_consultant_number = fields.Char(string="DATEV Consultant Number")
    datev_client_number = fields.Char(string="DATEV Client Number")
    datev_account_number_length = fields.Selection(
        [("4", "4"), ("5", "5"), ("6", "6"), ("7", "7"), ("8", "8")],
        string="DATEV Account Number Length",
        default="4",
    )

    def datev_get_client_id(self):
        """Return the DATEV client-id ('consultant-client') for this company."""
        self.ensure_one()
        if not self.datev_consultant_number or not self.datev_client_number:
            raise UserError(_(
                "DATEV: Bitte Consultant Number und Client Number für Firma "
                "'%s' in den Einstellungen (DATEV Cloud) hinterlegen."
            ) % self.name)
        return f"{self.datev_consultant_number}-{self.datev_client_number}"
