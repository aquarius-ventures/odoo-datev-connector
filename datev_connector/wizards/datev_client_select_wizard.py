from odoo import _, fields, models
from odoo.exceptions import UserError


def _services_to_str(client: dict) -> str:
    services = client.get("services") or []
    names = []
    for service in services:
        if isinstance(service, dict):
            names.append(service.get("name") or str(service))
        else:
            names.append(str(service))
    return ", ".join(n for n in names if n)


def _has_accounting_service(services_str: str) -> bool:
    lowered = (services_str or "").lower()
    return "extf" in lowered or "buchungsdaten" in lowered or "accounting" in lowered


class DatevClientSelectWizard(models.TransientModel):
    """Scrollable client list (MUST for the list variant of the authorization
    check): company name + consultant/client number + booked services; the
    selection is taken over into the company."""

    _name = "datev.client.select.wizard"
    _description = "DATEV Mandant auswählen"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    line_ids = fields.One2many("datev.client.select.wizard.line", "wizard_id")


class DatevClientSelectWizardLine(models.TransientModel):
    _name = "datev.client.select.wizard.line"
    _description = "DATEV Mandant auswählen — Zeile"
    _order = "consultant_number, client_number"

    wizard_id = fields.Many2one("datev.client.select.wizard", required=True, ondelete="cascade")
    name = fields.Char(string="Firma", readonly=True)
    consultant_number = fields.Char(string="Beraternummer", readonly=True)
    client_number = fields.Char(string="Mandantennummer", readonly=True)
    services = fields.Char(string="Gebuchte Services", readonly=True)

    def action_select(self):
        self.ensure_one()
        company = self.wizard_id.company_id
        if not self.consultant_number or not self.client_number:
            raise UserError(_("Dieser Eintrag enthält keine vollständige Berater-/Mandantennummer."))
        has_service = _has_accounting_service(self.services)
        company.write({
            "datev_consultant_number": self.consultant_number,
            "datev_client_number": self.client_number,
            "datev_client_verified": has_service,
            "datev_client_check_info": (
                "%s — Services: %s" % (self.name or "?", self.services or "–")
            )[:250],
        })
        if not has_service:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("DATEV"),
                    "message": _(
                        "Mandant übernommen, aber der Buchungsdatenservice ist für "
                        "diesen Mandanten nicht gebucht. Bitte beim Steuerberater/"
                        "DATEV aktivieren lassen: http://go.datev.de/datenservices-einrichten"
                    ),
                    "type": "warning",
                    "sticky": True,
                },
            }
        return {"type": "ir.actions.act_window_close"}
