from odoo import api, fields, models

# Default transfer channel per compensation category.
_CATEGORY_DEFAULT_CHANNEL = {
    "fest_regelmaessig": "gross_payment",
    "fest_unregelmaessig": "gross_payment",
    "variabel_zeit": "month_record",
    "variabel_aufgabe": "month_record",
    "zulage_zeit": "month_record",
}


class DatevSalaryType(models.Model):
    """DATEV Lohnart catalog & mapping (per company / Mandant)."""

    _name = "datev.salary.type"
    _description = "DATEV Lohnart (Salary Type)"
    _order = "code"

    code = fields.Char(
        string="Lohnart (DATEV)",
        required=True,
        help="DATEV salary_type_id (1–9999), z. B. 11 für Grundlohn.",
    )
    name = fields.Char(string="Bezeichnung", required=True)
    category = fields.Selection(
        [
            ("fest_regelmaessig", "Fest / regelmäßig"),
            ("fest_unregelmaessig", "Fest / unregelmäßig"),
            ("variabel_zeit", "Variabel / zeitbasiert"),
            ("variabel_aufgabe", "Variabel / aufgabenbasiert"),
            ("zulage_zeit", "Zeitabhängige Zulage"),
        ],
        string="Kategorie",
        required=True,
        default="variabel_zeit",
    )
    channel = fields.Selection(
        [
            ("month_record", "Bewegungsdaten (month-records)"),
            ("gross_payment", "Feste Bezüge (gross-payments)"),
            ("hourly_wage", "Stundenlohn (hourly-wages)"),
        ],
        string="DATEV-Kanal",
        required=True,
        default="month_record",
        help="Über welchen API-Kanal diese Lohnart übertragen wird. "
             "Default aus der Kategorie, aber überschreibbar.",
    )
    external_key = fields.Char(
        string="Externer Schlüssel",
        help="Optionaler Alias, falls der Import einen anderen Schlüssel als die "
             "DATEV-Lohnart nutzt.",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        ondelete="cascade",
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "unique_code_company",
            "UNIQUE(code, company_id)",
            "Jede Lohnart darf pro Company nur einmal existieren.",
        ),
    ]

    @api.onchange("category")
    def _onchange_category_set_channel(self):
        for rec in self:
            default = _CATEGORY_DEFAULT_CHANNEL.get(rec.category)
            if default:
                rec.channel = default
