from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    datev_target_system = fields.Selection(
        related="company_id.datev_target_system", readonly=False,
    )
