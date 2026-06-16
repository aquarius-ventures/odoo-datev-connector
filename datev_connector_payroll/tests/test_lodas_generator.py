from odoo.tests.common import TransactionCase


class TestLodasGenerator(TransactionCase):

    def _make_generator(self):
        from odoo.addons.datev_connector_payroll.services.lodas_generator import LodasGenerator

        return LodasGenerator(self.env, self.env.company)

    def test_generate_empty_produces_header_and_footer(self):
        gen = self._make_generator()
        result = gen.generate(self.env["hr.payslip"]).decode("cp1252")
        self.assertIn("[Allgemein]", result)
        self.assertIn("[Ende]", result)
