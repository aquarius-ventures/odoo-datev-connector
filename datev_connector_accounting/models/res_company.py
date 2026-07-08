from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    datev_extf_festschreibung = fields.Boolean(
        string="DATEV Festschreibung",
        default=True,
        help="Header field 21 of exported EXTF files. Enabled (default) means "
             "postings are fixated on import — the GoBD-compliant setting. "
             "Only disable this in coordination with the tax advisor.",
    )
    datev_chart_of_accounts = fields.Selection(
        [("03", "SKR03"), ("04", "SKR04")],
        string="DATEV Sachkontenrahmen",
        help="G/L chart of accounts used in DATEV (EXTF header field 27).",
    )
