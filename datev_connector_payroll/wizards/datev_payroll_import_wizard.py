import base64
import csv
import io
import json

from odoo import _, fields, models
from odoo.exceptions import UserError


class DatevPayrollImportWizard(models.TransientModel):
    _name = "datev.payroll.import.wizard"
    _description = "DATEV Lohndaten-Import (JSON / CSV)"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    run_id = fields.Many2one(
        "datev.payroll.run",
        help="Wenn gesetzt, werden die Zeilen an diesen Lauf angehängt; sonst neuer Lauf.",
    )
    reference_date = fields.Char(
        string="Abrechnungsmonat",
        help="Format yyyy-MM. Für CSV-Import erforderlich; bei JSON optional " "(überschreibt den Wert aus der Datei).",
    )
    data_file = fields.Binary(string="Datei (JSON oder CSV)", required=True)
    filename = fields.Char()

    @staticmethod
    def _parse_number(val):
        """Parse a JSON number or a German-formatted string ('1.234,56') to float."""
        if val in (None, ""):
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if not s:
            return 0.0
        if "," in s:  # German format: '.' = thousands, ',' = decimal
            s = s.replace(".", "").replace(",", ".")
        return float(s)

    # ------------------------------------------------------------------
    def action_import(self):
        self.ensure_one()
        raw = base64.b64decode(self.data_file)
        is_csv = (self.filename or "").lower().endswith(".csv") or (
            not (self.filename or "").lower().endswith(".json") and not raw.lstrip().startswith(b"{")
        )
        if is_csv:
            rows, ref_date = self._read_csv(raw)
        else:
            rows, ref_date = self._read_json(raw)

        ref_date = self.reference_date or ref_date or fields.Date.today().strftime("%Y-%m")

        run = self.run_id
        if not run:
            run = self.env["datev.payroll.run"].create(
                {
                    "company_id": self.company_id.id,
                    "reference_date": ref_date,
                    "target_system": self.company_id.datev_target_system,
                }
            )

        if not rows:
            raise UserError(_("Keine Zeilen in der Datei gefunden."))

        run.write({"line_ids": self._to_commands(run, rows), "state": "imported"})
        run.line_ids._validate()
        return {
            "type": "ir.actions.act_window",
            "res_model": "datev.payroll.run",
            "res_id": run.id,
            "view_mode": "form",
            "target": "current",
        }

    # ------------------------------------------------------------------
    def _read_json(self, raw):
        """Return (rows, reference_date). Each row is a normalized dict."""
        try:
            data = json.loads(raw)
        except Exception as exc:
            raise UserError(_("JSON konnte nicht gelesen werden: %s") % exc)
        rows = []
        for emp in data.get("employees", []):
            pnr = emp.get("personnel_number")
            for ln in emp.get("lines", []):
                rows.append(
                    {
                        "personnel_number": pnr,
                        "salary_type": ln.get("salary_type"),
                        "value": ln.get("value"),
                        "factor": ln.get("factor"),
                        "amount": ln.get("amount"),
                        "cost_center": ln.get("cost_center"),
                        "processing_key": ln.get("processing_key"),
                        "payment_months": ln.get("payment_months"),
                    }
                )
        return rows, data.get("reference_date")

    def _read_csv(self, raw):
        """Portal CSV: employee_no;factor;bs;cost_center;loan_type;amount (';', dt. Dezimal)."""
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        rows = []
        for r in reader:
            if not (r.get("employee_no") or r.get("loan_type")):
                continue
            rows.append(
                {
                    "personnel_number": r.get("employee_no"),
                    "salary_type": r.get("loan_type"),
                    "value": r.get("factor"),  # CSV 'factor' → value
                    "factor": r.get("amount"),  # CSV 'amount' → differing_factor
                    "amount": None,
                    "cost_center": r.get("cost_center"),
                    "processing_key": r.get("bs"),
                    "payment_months": None,
                }
            )
        return rows, None

    # ------------------------------------------------------------------
    def _to_commands(self, run, rows):
        Employee = self.env["hr.employee"]
        SalaryType = self.env["datev.salary.type"]
        emp_cache, st_cache = {}, {}

        def _emp(pnr):
            key = str(pnr)
            if key not in emp_cache:
                emp_cache[key] = Employee.search(
                    [
                        ("datev_personnel_number", "=", key),
                        ("company_id", "in", [run.company_id.id, False]),
                    ],
                    limit=1,
                )
            return emp_cache[key]

        def _st(code):
            key = str(code)
            if key not in st_cache:
                st_cache[key] = SalaryType.search(
                    [
                        ("company_id", "=", run.company_id.id),
                        "|",
                        ("code", "=", key),
                        ("external_key", "=", key),
                    ],
                    limit=1,
                )
            return st_cache[key]

        commands = []
        for row in rows:
            pnr = row.get("personnel_number")
            code = row.get("salary_type")
            emp = _emp(pnr) if pnr is not None and str(pnr) != "" else Employee
            st = _st(code) if code is not None and str(code) != "" else SalaryType
            pk = row.get("processing_key")
            commands.append(
                (
                    0,
                    0,
                    {
                        "personnel_number": str(pnr) if pnr not in (None, "") else False,
                        "employee_id": emp.id if emp else False,
                        "salary_type_code": str(code) if code not in (None, "") else False,
                        "salary_type_id": st.id if st else False,
                        "value": self._parse_number(row.get("value")),
                        "factor": self._parse_number(row.get("factor")),
                        "amount": self._parse_number(row.get("amount")),
                        "cost_center": row.get("cost_center") or False,
                        "processing_key": str(pk) if pk not in (None, "") else False,
                        "payment_months": row.get("payment_months") or False,
                        "source": "imported",
                    },
                )
            )
        return commands
