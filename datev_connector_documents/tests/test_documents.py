from datetime import date
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase


class TestDatevDocuments(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.datev_service_documents = True
        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1
        )
        cls.account_cash = cls.env["account.account"].search(
            [("account_type", "=", "asset_cash"), ("company_id", "=", cls.company.id)], limit=1
        )
        cls.account_income = cls.env["account.account"].search(
            [("account_type", "=", "income"), ("company_id", "=", cls.company.id)], limit=1
        )

    def _make_move_with_attachment(self):
        move = self.env["account.move"].create(
            {
                "journal_id": self.journal.id,
                "date": date(2025, 1, 15),
                "line_ids": [
                    (0, 0, {"account_id": self.account_cash.id, "debit": 100.0, "credit": 0.0}),
                    (0, 0, {"account_id": self.account_income.id, "debit": 0.0, "credit": 100.0}),
                ],
            }
        )
        move.action_post()
        attachment = self.env["ir.attachment"].create(
            {
                "name": "Beleg.pdf",
                "raw": b"%PDF-1.4 test voucher",
                "res_model": "account.move",
                "res_id": move.id,
            }
        )
        move.message_main_attachment_id = attachment
        return move

    def test_assign_guid_and_beleglink_in_extf(self):
        from odoo.addons.datev_connector_accounting.services.extf_generator import ExtfGenerator

        move = self._make_move_with_attachment()
        move._datev_assign_document_guids()
        guid = move.datev_document_guid
        self.assertTrue(guid)
        # stable across repeated calls (no duplicate uploads possible)
        move._datev_assign_document_guids()
        self.assertEqual(move.datev_document_guid, guid)

        gen = ExtfGenerator(self.env, self.company, date(2025, 1, 1), date(2025, 1, 31))
        content = gen.generate(move).decode("cp1252")
        row = content.split("\r\n")[2].split(";")
        # Beleglink column 20: BEDI "<guid>" with inner quotes doubled
        self.assertEqual(row[19], '"BEDI ""%s"""' % guid)

    def test_no_service_flag_no_guid(self):
        self.company.datev_service_documents = False
        move = self._make_move_with_attachment()
        move._datev_assign_document_guids()
        self.assertFalse(move.datev_document_guid)
        self.company.datev_service_documents = True

    def test_no_attachment_no_guid(self):
        move = self.env["account.move"].create(
            {
                "journal_id": self.journal.id,
                "date": date(2025, 1, 16),
                "line_ids": [
                    (0, 0, {"account_id": self.account_cash.id, "debit": 50.0, "credit": 0.0}),
                    (0, 0, {"account_id": self.account_income.id, "debit": 0.0, "credit": 50.0}),
                ],
            }
        )
        move.action_post()
        move._datev_assign_document_guids()
        self.assertFalse(move.datev_document_guid)

    def test_metadata_has_all_three_repository_levels(self):
        move = self._make_move_with_attachment()
        metadata = move._datev_document_metadata()
        self.assertTrue(metadata["category"])
        self.assertTrue(metadata["folder"])
        self.assertEqual(metadata["register"], "2025/01")

    def test_upload_documents_is_idempotent(self):
        move = self._make_move_with_attachment()
        service = MagicMock()
        move._datev_upload_documents(service, "455148-1")
        service.documents_upload.assert_called_once()
        args, _kwargs = service.documents_upload.call_args
        self.assertEqual(args[0], "455148-1")
        self.assertEqual(args[1], move.datev_document_guid)
        self.assertEqual(args[2], "Beleg.pdf")
        self.assertEqual(args[3], b"%PDF-1.4 test voucher")
        self.assertEqual(args[4]["register"], "2025/01")
        self.assertTrue(move.datev_document_uploaded_at)
        # second run: already uploaded, no new call
        move._datev_upload_documents(service, "455148-1")
        service.documents_upload.assert_called_once()

    def test_scope_includes_documents(self):
        from odoo.addons.datev_connector.services.datev_api import DatevApiService

        self.company.datev_service_accounting = True
        service = DatevApiService(
            self.env,
            {"client_id": "x", "client_secret": "y", "sandbox": True},
        )
        scopes = service.get_scope().split()
        self.assertIn("accounting:documents", scopes)
        self.assertIn("accounting:clients:read", scopes)
        self.company.datev_service_documents = False
        self.assertNotIn("accounting:documents", service.get_scope().split())
        self.company.datev_service_documents = True
