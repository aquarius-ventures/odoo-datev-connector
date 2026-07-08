from odoo import _, fields, models


class DatevPayrollLine(models.Model):
    """A single payroll line (movement/fixed/hourly) within a run."""

    _name = "datev.payroll.line"
    _description = "DATEV Lohnlauf-Zeile"

    run_id = fields.Many2one("datev.payroll.run", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="run_id.company_id", store=True)
    employee_id = fields.Many2one("hr.employee", string="Mitarbeiter")
    personnel_number = fields.Char(string="Personalnr.")
    salary_type_id = fields.Many2one(
        "datev.salary.type",
        string="Lohnart",
        domain="[('company_id', '=', company_id)]",
    )
    salary_type_code = fields.Char(string="Lohnart-Code")
    value = fields.Float(string="Menge/Wert", help="→ DATEV month-record 'value'.")
    factor = fields.Float(string="Faktor", help="→ DATEV month-record 'differing_factor' (0–99,99).")
    amount = fields.Float(string="Betrag", help="Für feste Bezüge (gross-payments).")
    cost_center = fields.Char(string="Kostenstelle")
    processing_key = fields.Char(
        string="Bearbeitungsschlüssel",
        help="bs aus dem Import — wird derzeit NICHT an die API gesendet " "(kein Feld im month-records-Schema).",
    )
    payment_months = fields.Char(string="Zahlungsmonate", help="Für gross-payments, z. B. 1,2,…,12.")
    source = fields.Selection([("imported", "Importiert"), ("manual", "Manuell")], default="manual")
    channel = fields.Selection(related="salary_type_id.channel", string="Kanal")
    error = fields.Char(string="Fehler", readonly=True)

    def _validate(self):
        """Flag per-line problems in `error` (unknown salary type, unmatched employee, bounds)."""
        for line in self:
            problems = []
            if not line.salary_type_id:
                problems.append(_("Lohnart '%s' unbekannt") % (line.salary_type_code or "?"))
            if not line.employee_id:
                problems.append(_("Mitarbeiter/Personalnr. '%s' nicht gefunden") % (line.personnel_number or "?"))
            if not (-999999.99 <= line.value <= 999999.99):
                problems.append(_("Wert außerhalb −999.999,99…999.999,99"))
            if line.channel == "month_record" and not (0 <= line.factor <= 99.99):
                problems.append(_("Faktor außerhalb 0–99,99"))
            line.error = "; ".join(problems) or False
