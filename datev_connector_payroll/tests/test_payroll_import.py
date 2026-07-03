import base64
import json

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPayrollImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.datev_target_system = "lodas"
        cls.Wizard = cls.env["datev.payroll.import.wizard"]
        # Catalog
        cls.st_11 = cls.env["datev.salary.type"].create({
            "company_id": cls.company.id, "code": "11", "name": "Grundlohn",
            "category": "variabel_zeit", "channel": "month_record",
        })
        cls.st_10 = cls.env["datev.salary.type"].create({
            "company_id": cls.company.id, "code": "10", "name": "Gehalt",
            "category": "fest_regelmaessig", "channel": "gross_payment",
        })
        # Employee matched by personnel number
        cls.emp = cls.env["hr.employee"].sudo().create({
            "name": "Test Mitarbeiter", "company_id": cls.company.id,
            "datev_personnel_number": "7009",
        })

    def _run_import(self, payload):
        wiz = self.Wizard.create({
            "company_id": self.company.id,
            "json_file": base64.b64encode(json.dumps(payload).encode()),
            "filename": "test.json",
        })
        action = wiz.action_import()
        return self.env["datev.payroll.run"].browse(action["res_id"])

    # ── number parsing ───────────────────────────────────────────────────────
    def test_parse_number(self):
        p = self.Wizard._parse_number
        self.assertEqual(p(160), 160.0)
        self.assertEqual(p(13.9), 13.9)
        self.assertEqual(p("601,69"), 601.69)
        self.assertEqual(p("1.234,56"), 1234.56)
        self.assertEqual(p(""), 0.0)
        self.assertEqual(p(None), 0.0)

    # ── import: matching, german decimals, unknown code ──────────────────────
    def test_import_creates_run_and_lines(self):
        run = self._run_import({
            "reference_date": "2026-01",
            "employees": [
                {"personnel_number": 7009, "lines": [
                    {"salary_type": "11", "value": "160", "factor": "13,9", "processing_key": "1"},
                    {"salary_type": "10", "value": 3500, "cost_center": "0"},
                    {"salary_type": "9999", "value": 5},
                ]},
            ],
        })
        self.assertEqual(run.reference_date, "2026-01")
        self.assertEqual(run.state, "imported")
        self.assertEqual(run.line_count, 3)

        by_code = {l.salary_type_code: l for l in run.line_ids}
        # matched line
        l11 = by_code["11"]
        self.assertEqual(l11.salary_type_id, self.st_11)
        self.assertEqual(l11.employee_id, self.emp)
        self.assertEqual(l11.value, 160.0)
        self.assertEqual(l11.factor, 13.9)  # german "13,9"
        self.assertEqual(l11.channel, "month_record")
        self.assertFalse(l11.error)
        # unknown code line → flagged
        l99 = by_code["9999"]
        self.assertFalse(l99.salary_type_id)
        self.assertTrue(l99.error)
        self.assertEqual(run.error_count, 1)

    def test_import_unmatched_employee_flagged(self):
        run = self._run_import({
            "reference_date": "2026-01",
            "employees": [
                {"personnel_number": 8888, "lines": [{"salary_type": "11", "value": 10}]},
            ],
        })
        line = run.line_ids
        self.assertFalse(line.employee_id)
        self.assertTrue(line.error)

    # ── target_system guard ──────────────────────────────────────────────────
    def test_validate_requires_target_system(self):
        run = self._run_import({
            "reference_date": "2026-01",
            "employees": [{"personnel_number": 7009, "lines": [{"salary_type": "11", "value": 10}]}],
        })
        self.company.datev_target_system = False
        with self.assertRaises(UserError):
            run.action_validate()
        # with target system + clean lines → validated
        self.company.datev_target_system = "lodas"
        run.action_validate()
        self.assertEqual(run.state, "validated")

    def test_transfer_blocked_in_p2(self):
        run = self._run_import({
            "reference_date": "2026-01",
            "employees": [{"personnel_number": 7009, "lines": [{"salary_type": "11", "value": 10}]}],
        })
        with self.assertRaises(UserError):
            run.action_transfer()
