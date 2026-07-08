from odoo import fields, models


class DatevTaxMapping(models.Model):
    """Maps an Odoo tax to a DATEV BU-Schlüssel (posting key).

    When every tax on a move has a BU key, the EXTF export writes gross rows
    with the BU key (DATEV standard, automatic accounts recompute the tax).
    Without a complete mapping, tax lines are exported as separate rows.
    """

    _name = "datev.tax.mapping"
    _description = "DATEV Tax Mapping (BU-Schlüssel)"
    _rec_name = "tax_id"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        ondelete="cascade",
        default=lambda self: self.env.company,
    )
    tax_id = fields.Many2one(
        "account.tax",
        string="Odoo Tax",
        required=True,
        ondelete="cascade",
        domain="[('company_id', '=', company_id)]",
    )
    datev_bu_key = fields.Char(
        string="BU-Schlüssel",
        required=True,
        size=4,
        help="DATEV posting key (column 9), e.g. 3 = 19% USt, 2 = 7% USt, " "9 = 19% Vorsteuer, 8 = 7% Vorsteuer.",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "unique_tax_company",
            "UNIQUE(tax_id, company_id)",
            "Each Odoo tax can only have one DATEV BU key per company.",
        ),
    ]
