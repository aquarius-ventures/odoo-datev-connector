from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    datev_extf_festschreibung = fields.Boolean(
        related="company_id.datev_extf_festschreibung", readonly=False,
    )
    datev_chart_of_accounts = fields.Selection(
        related="company_id.datev_chart_of_accounts", readonly=False,
    )
