from datetime import date
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


class TestHrJobStatus(TransactionCase):
    """Tests for hr:exchange job-status polling (_poll_datev_hr_jobs / _extract_job_errors)."""

    def setUp(self):
        super().setUp()
        # datev_get_client_id() needs consultant + client number on the company.
        self.env.company.write({
            "datev_consultant_number": "455148",
            "datev_client_number": "1",
        })

    def _make_pending_emp(self):
        emp = self.env["hr.employee"].sudo().create({
            "name": "Maria Schmidt",
            "datev_personnel_number": "42",
            "datev_job_id": "ce2ccb10-3bc9-48c3-a75b-dcbe88f847ae",
            "datev_job_state": "pending",
        })
        return emp

    def _poll_with_response(self, emp, response):
        """Run _poll_datev_hr_jobs with the API service mocked to return `response`."""
        fake_service = MagicMock()
        fake_service.hr_exchange_job_status.return_value = response
        settings_model = type(self.env["res.config.settings"])
        with patch(
            "odoo.addons.datev_connector.services.datev_api.DatevApiService",
            return_value=fake_service,
        ), patch.object(
            settings_model, "_get_datev_config",
            lambda self, company=None: {}, create=True,
        ):
            emp._poll_datev_hr_jobs()

    # ── State outcomes ───────────────────────────────────────────────────────
    def test_completed_marks_succeeded(self):
        emp = self._make_pending_emp()
        self._poll_with_response(emp, {"state": "completed", "errors": []})
        self.assertEqual(emp.datev_job_state, "succeeded")
        self.assertFalse(emp.datev_job_error)

    def test_failed_marks_failed_with_error(self):
        emp = self._make_pending_emp()
        self._poll_with_response(emp, {
            "state": "failed",
            "errors": [{"code": "DCO1234", "client_message": "Ungültige SV-Nummer"}],
        })
        self.assertEqual(emp.datev_job_state, "failed")
        self.assertIn("Ungültige SV-Nummer", emp.datev_job_error)
        self.assertIn("DCO1234", emp.datev_job_error)

    def test_completed_with_errors_is_failed(self):
        emp = self._make_pending_emp()
        self._poll_with_response(emp, {
            "state": "completed",
            "errors": [{"message": "Teilweise abgelehnt"}],
        })
        self.assertEqual(emp.datev_job_state, "failed")
        self.assertIn("Teilweise abgelehnt", emp.datev_job_error)

    def test_unknown_state_stays_pending(self):
        emp = self._make_pending_emp()
        self._poll_with_response(emp, {"state": "processing"})
        self.assertEqual(emp.datev_job_state, "pending")

    def test_accepted_state_stays_pending(self):
        emp = self._make_pending_emp()
        self._poll_with_response(emp, {"state": "accepted", "errors": []})
        self.assertEqual(emp.datev_job_state, "pending")

    # ── _extract_job_errors helper ───────────────────────────────────────────
    def test_extract_job_errors_variants(self):
        Emp = self.env["hr.employee"]
        self.assertFalse(Emp._extract_job_errors({"errors": []}))
        self.assertEqual(
            Emp._extract_job_errors({"errors": [{"message": "Boom"}]}), "Boom"
        )
        self.assertEqual(
            Emp._extract_job_errors({"errors": [{"code": "E1", "client_message": "Boom"}]}),
            "[E1] Boom",
        )
        # dict instead of list
        self.assertEqual(
            Emp._extract_job_errors({"errors": {"technical_message": "Kaputt"}}), "Kaputt"
        )
        # plain strings
        self.assertEqual(
            Emp._extract_job_errors({"messages": ["a", "b"]}), "a\nb"
        )
