from odoo import fields, models


class DatevEmployeeMapping(models.Model):
    """Links an Odoo employee to a DATEV personnel number (Personalnummer)."""

    _name = "datev.employee.mapping"
    _description = "DATEV Employee Mapping"
    _rec_name = "employee_id"

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        ondelete="cascade",
    )
    datev_personnel_number = fields.Char(
        string="DATEV Personalnummer",
        required=True,
        help="Unique personnel number used in DATEV LODAS / Lohn und Gehalt.",
    )
    datev_consultant_number = fields.Char(
        string="DATEV Beraternummer",
        help="Overrides the global consultant number for this employee if set.",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "unique_employee",
            "UNIQUE(employee_id)",
            "Each employee can only have one DATEV mapping.",
        ),
        (
            "unique_personnel_number",
            "UNIQUE(datev_personnel_number)",
            "DATEV Personalnummer must be unique.",
        ),
    ]
