from odoo.tests.common import TransactionCase


class TestExtfParser(TransactionCase):
    def _make_parser(self):
        from odoo.addons.datev_connector_accounting.services.extf_parser import ExtfParser

        return ExtfParser()

    def test_parse_valid_extf(self):
        sample = (
            "EXTF;700;21;Buchungsstapel;7;;;;;;1001;10001;4;20250101;20250101;20250131\n"
            "Umsatz (ohne Soll/Haben-Kz);Soll/Haben-Kennzeichen;Konto;Gegenkonto\n"
            "100,00;S;1200;4400\n"
        ).encode("utf-8")
        parser = self._make_parser()
        result = parser.parse(sample)
        self.assertEqual(result["entries"][0]["Konto"], "1200")

    def test_parse_invalid_raises(self):
        parser = self._make_parser()
        with self.assertRaises(ValueError):
            parser.parse(b"not a datev file")

    def test_parse_cp1252_file(self):
        """Real DATEV exports are usually CP1252 — must not crash on umlauts."""
        sample = (
            "EXTF;700;21;Buchungsstapel;13;;;;;;1001;10001;4;20250101;20250101;20250131\r\n"
            "Umsatz (ohne Soll/Haben-Kz);Soll/Haben-Kennzeichen;Konto;Buchungstext\r\n"
            "100,00;S;1200;Bürobedarf für Großhändler\r\n"
        ).encode("cp1252")
        parser = self._make_parser()
        result = parser.parse(sample)
        self.assertEqual(result["entries"][0]["Buchungstext"], "Bürobedarf für Großhändler")
