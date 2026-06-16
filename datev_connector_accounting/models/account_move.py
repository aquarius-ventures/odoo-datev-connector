import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    datev_exported = fields.Boolean(
        string="Exported to DATEV",
        default=False,
        copy=False,
        help="Set after a successful EXTF export to DATEV Cloud.",
    )
    datev_export_date = fields.Datetime(
        string="DATEV Export Date",
        copy=False,
        readonly=True,
    )

    def action_datev_export_single(self):
        self.ensure_one()
        if self.state != "posted":
            raise UserError(_("Only posted journal entries can be exported to DATEV."))
        wizard = self.env["datev.export.wizard"].create({"move_ids": [(4, self.id)]})
        return wizard.action_export()
