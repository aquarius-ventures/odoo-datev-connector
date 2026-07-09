from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestExtfGenerator(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1
        )
        cls.account_cash = cls.env["account.account"].search(
            [("account_type", "=", "asset_cash"), ("company_id", "=", cls.company.id)], limit=1
        )
        cls.account_income = cls.env["account.account"].search(
            [("account_type", "=", "income"), ("company_id", "=", cls.company.id)], limit=1
        )
        cls.account_receivable = cls.env["account.account"].search(
            [("account_type", "=", "asset_receivable"), ("company_id", "=", cls.company.id)], limit=1
        )

    def _make_generator(self, date_from=None, date_to=None):
        from odoo.addons.datev_connector_accounting.services.extf_generator import ExtfGenerator

        return ExtfGenerator(
            self.env,
            self.company,
            date_from or date(2025, 1, 1),
            date_to or date(2025, 1, 31),
        )

    def _make_simple_move(self, text="Testbuchung", amount=100.0):
        move = self.env["account.move"].create(
            {
                "journal_id": self.journal.id,
                "date": date(2025, 1, 15),
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "account_id": self.account_cash.id,
                            "debit": amount,
                            "credit": 0.0,
                            "name": text,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "account_id": self.account_income.id,
                            "debit": 0.0,
                            "credit": amount,
                            "name": text,
                        },
                    ),
                ],
            }
        )
        move.action_post()
        return move

    def _decode(self, csv_bytes):
        return csv_bytes.decode("cp1252")

    def test_generate_raises_on_empty_moves(self):
        gen = self._make_generator()
        with self.assertRaises(UserError):
            gen.generate(self.env["account.move"])

    def test_header_v13_structure(self):
        move = self._make_simple_move()
        content = self._decode(self._make_generator().generate(move))
        lines = content.split("\r\n")
        header = lines[0].split(";")
        self.assertEqual(header[0], '"EXTF"')
        self.assertEqual(header[1], "700")
        self.assertEqual(header[2], "21")
        self.assertEqual(header[3], '"Buchungsstapel"')
        self.assertEqual(header[4], "13")
        self.assertEqual(len(header), 31)
        # Field 6 "Erzeugt am": 17-digit timestamp, must not be empty
        self.assertRegex(header[5], r"^20\d{15}$")
        # Field 17 Bezeichnung filled and quoted
        self.assertTrue(header[16].startswith('"') and len(header[16]) > 2)
        # Field 21 Festschreibung defaults to 1
        self.assertEqual(header[20], "1")

    def test_festschreibung_configurable(self):
        self.company.datev_extf_festschreibung = False
        move = self._make_simple_move()
        header = self._decode(self._make_generator().generate(move)).split("\r\n")[0]
        self.assertEqual(header.split(";")[20], "0")
        self.company.datev_extf_festschreibung = True

    def test_column_row_has_125_v13_columns(self):
        move = self._make_simple_move()
        content = self._decode(self._make_generator().generate(move))
        columns = content.split("\r\n")[1].split(";")
        self.assertEqual(len(columns), 125)
        self.assertEqual(columns[0], "Umsatz (ohne Soll/Haben-Kz)")
        self.assertEqual(columns[124], "Abw. Skontokonto")
        self.assertEqual(columns[121], "BVV-Position")

    def test_simple_move_exports_single_row(self):
        """Pivot logic: a 2-line move produces exactly ONE posting row, not two."""
        move = self._make_simple_move()
        content = self._decode(self._make_generator().generate(move))
        data_rows = [r for r in content.split("\r\n")[2:] if r]
        self.assertEqual(len(data_rows), 1)
        cells = data_rows[0].split(";")
        # Umsatz numeric with decimal comma, unquoted
        self.assertEqual(cells[0], "100,00")
        # Soll/Haben quoted
        self.assertIn(cells[1], ('"S"', '"H"'))
        # Konto/Gegenkonto unquoted digits
        self.assertNotIn('"', cells[6])
        self.assertNotIn('"', cells[7])
        # Belegdatum DDMM
        self.assertEqual(cells[9], "1501")
        # Buchungstext quoted
        self.assertTrue(cells[13].startswith('"') and cells[13].endswith('"'))
        self.assertEqual(len(cells), 125)

    def test_umlauts_survive_cp1252_roundtrip(self):
        move = self._make_simple_move(text="Bürobedarf für Großhändler ß")
        raw = self._make_generator().generate(move)
        content = raw.decode("cp1252")
        self.assertIn("Bürobedarf für Großhändler ß", content)
        # No stray newlines inside rows: total lines = header + columns + 1 row + trailing
        self.assertEqual(len(content.split("\r\n")), 4)

    def test_text_control_chars_stripped(self):
        move = self._make_simple_move(text="Zeile1\nZeile2\rTab\tEnde")
        content = self._decode(self._make_generator().generate(move))
        data_row = content.split("\r\n")[2]
        self.assertIn('"Zeile1 Zeile2 Tab Ende"', data_row)

    def test_belegfeld1_max_36_and_charset(self):
        move = self._make_simple_move()
        move.button_draft()
        move.ref = "RE 2025/001: äöü #" + "X" * 40
        move.action_post()
        content = self._decode(self._make_generator().generate(move))
        cells = content.split("\r\n")[2].split(";")
        belegfeld = cells[10].strip('"')
        self.assertLessEqual(len(belegfeld), 36)
        # Only allowed characters (spaces, umlauts, colons stripped)
        self.assertNotIn(" ", belegfeld)
        self.assertNotIn(":", belegfeld)
        self.assertNotIn("#", belegfeld)
        self.assertTrue(belegfeld.startswith("RE2025/001"))

    def test_fiscal_year_span_rejected(self):
        move = self._make_simple_move()
        gen = self._make_generator(date(2024, 12, 1), date(2025, 1, 31))
        with self.assertRaises(UserError):
            gen.generate(move)

    def test_invoice_gross_export_with_bu_key(self):
        """Variant B: with a BU mapping, an invoice exports one gross row per
        income line (no separate tax row → no double-booked revenue)."""
        tax = self.env["account.tax"].create(
            {
                "name": "USt 19% (Test)",
                "amount": 19.0,
                "type_tax_use": "sale",
                "company_id": self.company.id,
            }
        )
        self.env["datev.tax.mapping"].create(
            {
                "company_id": self.company.id,
                "tax_id": tax.id,
                "datev_bu_key": "3",
            }
        )
        partner = self.env["res.partner"].create({"name": "Testkunde"})
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "invoice_date": date(2025, 1, 20),
                "date": date(2025, 1, 20),
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Beratung",
                            "quantity": 1,
                            "price_unit": 100.0,
                            "account_id": self.account_income.id,
                            "tax_ids": [(6, 0, [tax.id])],
                        },
                    ),
                ],
            }
        )
        invoice.action_post()
        content = self._decode(self._make_generator().generate(invoice))
        data_rows = [r for r in content.split("\r\n")[2:] if r]
        self.assertEqual(len(data_rows), 1)
        cells = data_rows[0].split(";")
        # Gross amount 119.00, credit from the income line's perspective
        self.assertEqual(cells[0], "119,00")
        self.assertEqual(cells[1], '"H"')
        # BU key set (quoted text column)
        self.assertEqual(cells[8], '"3"')
        # Gegenkonto = receivable (pivot) account
        receivable_code = "".join(filter(str.isdigit, invoice.partner_id.property_account_receivable_id.code))
        self.assertEqual(cells[7], receivable_code)

    def test_invoice_without_bu_mapping_exports_tax_row(self):
        """Variant A fallback: without BU mapping the tax line becomes its own row."""
        tax = self.env["account.tax"].create(
            {
                "name": "USt 19% (Test unmapped)",
                "amount": 19.0,
                "type_tax_use": "sale",
                "company_id": self.company.id,
            }
        )
        partner = self.env["res.partner"].create({"name": "Testkunde 2"})
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "invoice_date": date(2025, 1, 21),
                "date": date(2025, 1, 21),
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Beratung",
                            "quantity": 1,
                            "price_unit": 100.0,
                            "account_id": self.account_income.id,
                            "tax_ids": [(6, 0, [tax.id])],
                        },
                    ),
                ],
            }
        )
        invoice.action_post()
        content = self._decode(self._make_generator().generate(invoice))
        data_rows = [r for r in content.split("\r\n")[2:] if r]
        self.assertEqual(len(data_rows), 2)
        amounts = sorted(r.split(";")[0] for r in data_rows)
        self.assertEqual(amounts, ["100,00", "19,00"])
