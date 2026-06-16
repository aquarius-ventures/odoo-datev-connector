from odoo import fields, models


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    datev_exported = fields.Boolean(
        string="Exported to DATEV",
        default=False,
        copy=False,
    )
    datev_export_date = fields.Datetime(
        string="DATEV Export Date",
        copy=False,
        readonly=True,
    )
