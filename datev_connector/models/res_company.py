from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = "res.company"

    # DATEV connection settings — per company, so one Odoo instance can talk to
    # several DATEV clients (Mandanten), one per company.
    # Field-level protection (DATEV MUST/DONT on sensitive data): the client
    # secret must never be readable by regular internal users via ORM reads.
    # Encryption at rest is provided by the hosting layer (odoo.sh volume
    # encryption); see dev/RELEASE_MEETING_NOTES.md.
    datev_client_id = fields.Char(
        string="DATEV Client ID",
        groups="base.group_system",
    )
    datev_client_secret = fields.Char(
        string="DATEV Client Secret",
        groups="base.group_system",
    )
    datev_sandbox_mode = fields.Boolean(string="DATEV Sandbox Mode")
    datev_consultant_number = fields.Char(string="DATEV Consultant Number")
    datev_client_number = fields.Char(string="DATEV Client Number")
    datev_account_number_length = fields.Selection(
        [("4", "4"), ("5", "5"), ("6", "6"), ("7", "7"), ("8", "8")],
        string="DATEV Account Number Length",
        default="4",
    )
    datev_last_error = fields.Char(
        string="DATEV Last Connection Error",
        readonly=True,
        help="Last error from the DATEV OAuth flow. Cleared on a successful connect.",
    )
    # Active data-service selection (DATEV MUST: only request the scopes the
    # customer needs, and the customer must actively choose the services).
    datev_service_accounting = fields.Boolean(
        string="DATEV Buchungsdatenservice",
        help="Fragt die Scopes datev:accounting:extf-files-import und "
        "datev:accounting:clients an. Der Buchungsdatenservice muss beim "
        "Steuerberater/DATEV bestellt und aktiviert sein: "
        "http://go.datev.de/datenservices-einrichten",
    )
    datev_service_hr = fields.Boolean(
        string="DATEV Lohnaustauschdatenservice (hr:exchange)",
        help="Fragt den Scope datev:hr:payrolldataexchange an. Der "
        "Lohnaustauschdatenservice muss beim Steuerberater/DATEV bestellt "
        "und aktiviert sein: http://go.datev.de/datenservices-einrichten",
    )

    datev_client_verified = fields.Boolean(
        string="DATEV Mandant geprüft",
        readonly=True,
        copy=False,
        help="Der Zugriff auf den Mandanten und der gebuchte Datenservice "
        "wurden über GET /clients/{client-id} bestätigt. Wird bei "
        "Änderung der Berater-/Mandantennummer zurückgesetzt.",
    )
    datev_client_check_info = fields.Char(
        string="DATEV Mandantenprüfung",
        readonly=True,
        copy=False,
    )

    def write(self, vals):
        # Changing the client identification invalidates a previous
        # authorization check.
        if {"datev_consultant_number", "datev_client_number"} & set(vals.keys()):
            vals.setdefault("datev_client_verified", False)
            vals.setdefault("datev_client_check_info", False)
        return super().write(vals)

    def _datev_module_installed(self, name):
        return bool(
            self.env["ir.module.module"].sudo().search_count([("name", "=", name), ("state", "=", "installed")])
        )

    def datev_get_service_accounting(self):
        self.ensure_one()
        return self.datev_service_accounting and self._datev_module_installed("datev_connector_accounting")

    def datev_get_service_hr(self):
        self.ensure_one()
        return self.datev_service_hr and self._datev_module_installed("datev_connector_hr")

    def datev_get_client_id(self):
        """Return the DATEV client-id ('consultant-client') for this company."""
        self.ensure_one()
        if not self.datev_consultant_number or not self.datev_client_number:
            raise UserError(
                _(
                    "DATEV: Bitte Consultant Number und Client Number für Firma "
                    "'%s' in den Einstellungen (DATEV Cloud) hinterlegen."
                )
                % self.name
            )
        return f"{self.datev_consultant_number}-{self.datev_client_number}"
