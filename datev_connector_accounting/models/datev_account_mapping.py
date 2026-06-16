from odoo import fields, models


class DatevAccountMapping(models.Model):
    """Maps an Odoo account to a DATEV Kontonummer."""

    _name = "datev.account.mapping"
    _description = "DATEV Account Mapping"
    _rec_name = "account_id"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        ondelete="cascade",
        default=lambda self: self.env.company,
    )
    account_id = fields.Many2one(
        "account.account",
        string="Odoo Account",
        required=True,
        ondelete="cascade",
        domain="[('company_id', '=', company_id)]",
    )
    datev_account_number = fields.Char(
        string="DATEV Konto",
        required=True,
        help="DATEV account number (Kontonummer), e.g. 1200 for Kasse",
    )
    datev_cost_center = fields.Char(
        string="DATEV Kostenstelle",
        help="Optional DATEV cost center (Kostenstelle / KSt)",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "unique_account_company",
            "UNIQUE(account_id, company_id)",
            "Each Odoo account can only have one DATEV mapping per company.",
        ),
    ]
