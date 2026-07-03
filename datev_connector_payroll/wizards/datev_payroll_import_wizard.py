import base64
import json

from odoo import _, fields, models
from odoo.exceptions import UserError


class DatevPayrollImportWizard(models.TransientModel):
    _name = "datev.payroll.import.wizard"
    _description = "DATEV Lohndaten-Import (JSON)"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    run_id = fields.Many2one(
        "datev.payroll.run",
        help="Wenn gesetzt, werden die Zeilen an diesen Lauf angehängt; sonst neuer Lauf.",
    )
    json_file = fields.Binary(string="JSON-Datei", required=True)
    filename = fields.Char()

    @staticmethod
    def _parse_number(val):
        """Parse a JSON number or a German-formatted string ('1.234,56') to float."""
        if val in (None, ""):
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if "," in s:  # German format: '.' = thousands, ',' = decimal
            s = s.replace(".", "").replace(",", ".")
        return float(s)

    def action_import(self):
        self.ensure_one()
        try:
            data = json.loads(base64.b64decode(self.json_file))
        except Exception as exc:
            raise UserError(_("JSON konnte nicht gelesen werden: %s") % exc)

        run = self.run_id
        if not run:
            run = self.env["datev.payroll.run"].create({
                "company_id": self.company_id.id,
                "reference_date": data.get("reference_date")
                or fields.Date.today().strftime("%Y-%m"),
                "target_system": self.company_id.datev_target_system,
            })

        Employee = self.env["hr.employee"]
        SalaryType = self.env["datev.salary.type"]
        emp_cache, st_cache = {}, {}

        def _find_employee(pnr):
            key = str(pnr)
            if key not in emp_cache:
                emp_cache[key] = Employee.search([
                    ("datev_personnel_number", "=", key),
                    ("company_id", "in", [run.company_id.id, False]),
                ], limit=1)
            return emp_cache[key]

        def _find_salary_type(code):
            key = str(code)
            if key not in st_cache:
                st_cache[key] = SalaryType.search([
                    ("company_id", "=", run.company_id.id),
                    "|", ("code", "=", key), ("external_key", "=", key),
                ], limit=1)
            return st_cache[key]

        commands = []
        for emp_block in data.get("employees", []):
            pnr = emp_block.get("personnel_number")
            emp = _find_employee(pnr) if pnr is not None else Employee
            for ln in emp_block.get("lines", []):
                code = ln.get("salary_type")
                st = _find_salary_type(code) if code is not None else SalaryType
                pk = ln.get("processing_key")
                commands.append((0, 0, {
                    "personnel_number": str(pnr) if pnr is not None else False,
                    "employee_id": emp.id if emp else False,
                    "salary_type_code": str(code) if code is not None else False,
                    "salary_type_id": st.id if st else False,
                    "value": self._parse_number(ln.get("value")),
                    "factor": self._parse_number(ln.get("factor")),
                    "amount": self._parse_number(ln.get("amount")),
                    "cost_center": ln.get("cost_center") or False,
                    "processing_key": str(pk) if pk is not None else False,
                    "payment_months": ln.get("payment_months") or False,
                    "source": "imported",
                }))

        if not commands:
            raise UserError(_("Keine Zeilen im JSON gefunden."))

        run.write({"line_ids": commands, "state": "imported"})
        run.line_ids._validate()

        return {
            "type": "ir.actions.act_window",
            "res_model": "datev.payroll.run",
            "res_id": run.id,
            "view_mode": "form",
            "target": "current",
        }
