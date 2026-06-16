from datetime import date

from odoo.tests.common import TransactionCase


class TestExtfGenerator(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

    def _make_generator(self, date_from=None, date_to=None):
        from odoo.addons.datev_connector_accounting.services.extf_generator import ExtfGenerator

        return ExtfGenerator(
            self.env,
            self.company,
            date_from or date(2025, 1, 1),
            date_to or date(2025, 1, 31),
        )

    def test_generate_raises_on_empty_moves(self):
        from odoo.exceptions import UserError

        gen = self._make_generator()
        with self.assertRaises(UserError):
            gen.generate(self.env["account.move"])

    def test_generated_csv_starts_with_extf(self):
        # Create a minimal posted move
        journal = self.env["account.journal"].search([("type", "=", "general")], limit=1)
        account = self.env["account.account"].search(
            [("account_type", "=", "asset_cash")], limit=1
        )
        account2 = self.env["account.account"].search(
            [("account_type", "=", "income")], limit=1
        )
        move = self.env["account.move"].create(
            {
                "journal_id": journal.id,
                "date": date(2025, 1, 15),
                "line_ids": [
                    (0, 0, {"account_id": account.id, "debit": 100.0, "credit": 0.0}),
                    (0, 0, {"account_id": account2.id, "debit": 0.0, "credit": 100.0}),
                ],
            }
        )
        move.action_post()
        gen = self._make_generator()
        csv_bytes = gen.generate(move)
        self.assertTrue(csv_bytes.decode("utf-8-sig").startswith("EXTF"))
