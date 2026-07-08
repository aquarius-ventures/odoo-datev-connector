from datetime import date
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


class TestHrJobStatus(TransactionCase):
    """Tests for hr:exchange job-status polling (_poll_datev_hr_jobs / _extract_job_errors)."""

    def setUp(self):
        super().setUp()
        # datev_get_client_id() needs consultant + client number on the company.
        self.env.company.write(
            {
                "datev_consultant_number": "455148",
                "datev_client_number": "1",
            }
        )

    def _make_pending_emp(self):
        emp = (
            self.env["hr.employee"]
            .sudo()
            .create(
                {
                    "name": "Maria Schmidt",
                    "datev_personnel_number": "42",
                    "datev_job_id": "ce2ccb10-3bc9-48c3-a75b-dcbe88f847ae",
                    "datev_job_state": "pending",
                }
            )
        )
        return emp

    def _poll_with_response(self, emp, response):
        """Run _poll_datev_hr_jobs with the API service mocked to return `response`."""
        fake_service = MagicMock()
        fake_service.hr_exchange_job_status.return_value = response
        settings_model = type(self.env["res.config.settings"])
        with (
            patch(
                "odoo.addons.datev_connector.services.datev_api.DatevApiService",
                return_value=fake_service,
            ),
            patch.object(
                settings_model,
                "_get_datev_config",
                lambda self, company=None: {},
                create=True,
            ),
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
        self._poll_with_response(
            emp,
            {
                "state": "failed",
                "errors": [{"code": "DCO1234", "client_message": "Ungültige SV-Nummer"}],
            },
        )
        self.assertEqual(emp.datev_job_state, "failed")
        self.assertIn("Ungültige SV-Nummer", emp.datev_job_error)
        self.assertIn("DCO1234", emp.datev_job_error)

    def test_completed_with_errors_is_failed(self):
        emp = self._make_pending_emp()
        self._poll_with_response(
            emp,
            {
                "state": "completed",
                "errors": [{"message": "Teilweise abgelehnt"}],
            },
        )
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

    # ── Fetch→Push state machine (read before write) ────────────────────────
    def _make_fetch_emp(self, personnel_number="42"):
        emp = (
            self.env["hr.employee"]
            .sudo()
            .create(
                {
                    "name": "Maria Schmidt",
                    "gender": "female",
                    "birthday": date(1990, 5, 1),
                    "ssnid": "12345678A123",
                    "datev_personnel_number": personnel_number,
                    "datev_tax_class": "1",
                    "datev_tax_id_number": "12345678901",
                    "datev_health_insurance_name": "87880235",
                    "datev_health_insurance_type": "gkv",
                    "datev_job_id": "ce2ccb10-3bc9-48c3-a75b-dcbe88f847ae",
                    "datev_job_state": "pending",
                    "datev_job_phase": "fetch",
                }
            )
        )
        return emp

    def _poll_fetch_with(self, emp, fetch_result):
        fake_service = MagicMock()
        fake_service.hr_exchange_job_status.return_value = {"state": "completed", "errors": []}
        fake_service.hr_exchange_job_result.return_value = fetch_result
        fake_service.hr_exchange_put_employee.return_value = {"id": "put-job-1", "state": "accepted"}
        fake_service.hr_exchange_post_employees.return_value = {"id": "post-job-1", "state": "accepted"}
        settings_model = type(self.env["res.config.settings"])
        with (
            patch(
                "odoo.addons.datev_connector.services.datev_api.DatevApiService",
                return_value=fake_service,
            ),
            patch.object(
                settings_model,
                "_get_datev_config",
                lambda self, company=None: {},
                create=True,
            ),
        ):
            emp._poll_datev_hr_jobs()
        return fake_service

    def test_fetch_existing_employee_triggers_put(self):
        emp = self._make_fetch_emp("42")
        service = self._poll_fetch_with(emp, {"employees": [{"personnel_number": 42}]})
        service.hr_exchange_put_employee.assert_called_once()
        service.hr_exchange_post_employees.assert_not_called()
        self.assertEqual(emp.datev_job_phase, "push")
        self.assertEqual(emp.datev_job_state, "pending")
        self.assertEqual(emp.datev_job_id, "put-job-1")
        # not yet verified → flag must stay False
        self.assertFalse(emp.datev_sync_created)

    def test_fetch_unknown_employee_triggers_post(self):
        emp = self._make_fetch_emp("43")
        service = self._poll_fetch_with(emp, {"employees": [{"personnel_number": 42}]})
        service.hr_exchange_post_employees.assert_called_once()
        service.hr_exchange_put_employee.assert_not_called()
        self.assertEqual(emp.datev_job_phase, "push")
        self.assertEqual(emp.datev_job_id, "post-job-1")
        self.assertFalse(emp.datev_sync_created)

    def test_push_success_sets_sync_created(self):
        emp = self._make_fetch_emp("42")
        emp.datev_job_phase = "push"
        fake_service = MagicMock()
        fake_service.hr_exchange_job_status.return_value = {"state": "completed", "errors": []}
        fake_service.hr_exchange_job_result.return_value = {"employees": [{"personnel_number": 42}]}
        settings_model = type(self.env["res.config.settings"])
        with (
            patch(
                "odoo.addons.datev_connector.services.datev_api.DatevApiService",
                return_value=fake_service,
            ),
            patch.object(
                settings_model,
                "_get_datev_config",
                lambda self, company=None: {},
                create=True,
            ),
        ):
            emp._poll_datev_hr_jobs()
        self.assertEqual(emp.datev_job_state, "succeeded")
        self.assertTrue(emp.datev_sync_created)
        fake_service.hr_exchange_job_result.assert_called_once()

    def test_push_success_with_result_errors_fails(self):
        emp = self._make_fetch_emp("42")
        emp.datev_job_phase = "push"
        fake_service = MagicMock()
        fake_service.hr_exchange_job_status.return_value = {"state": "completed", "errors": []}
        fake_service.hr_exchange_job_result.return_value = {
            "errors": [{"client_message": "Personalnummer bereits vergeben"}],
        }
        settings_model = type(self.env["res.config.settings"])
        with (
            patch(
                "odoo.addons.datev_connector.services.datev_api.DatevApiService",
                return_value=fake_service,
            ),
            patch.object(
                settings_model,
                "_get_datev_config",
                lambda self, company=None: {},
                create=True,
            ),
        ):
            emp._poll_datev_hr_jobs()
        self.assertEqual(emp.datev_job_state, "failed")
        self.assertIn("Personalnummer bereits vergeben", emp.datev_job_error)
        self.assertFalse(emp.datev_sync_created)

    def test_poll_cadence_min_age(self):
        """Jobs younger than 60 s must not be polled at all."""
        from odoo import fields as ofields

        emp = self._make_fetch_emp("42")
        emp.datev_job_created_at = ofields.Datetime.now()
        fake_service = MagicMock()
        settings_model = type(self.env["res.config.settings"])
        with (
            patch(
                "odoo.addons.datev_connector.services.datev_api.DatevApiService",
                return_value=fake_service,
            ),
            patch.object(
                settings_model,
                "_get_datev_config",
                lambda self, company=None: {},
                create=True,
            ),
        ):
            polled = emp._poll_datev_hr_jobs()
        self.assertEqual(polled, 0)
        fake_service.hr_exchange_job_status.assert_not_called()

    def test_poll_timeout_marks_failed(self):
        from datetime import timedelta

        from odoo import fields as ofields

        emp = self._make_fetch_emp("42")
        emp.datev_job_created_at = ofields.Datetime.now() - timedelta(minutes=20)
        fake_service = MagicMock()
        settings_model = type(self.env["res.config.settings"])
        with (
            patch(
                "odoo.addons.datev_connector.services.datev_api.DatevApiService",
                return_value=fake_service,
            ),
            patch.object(
                settings_model,
                "_get_datev_config",
                lambda self, company=None: {},
                create=True,
            ),
        ):
            emp._poll_datev_hr_jobs()
        self.assertEqual(emp.datev_job_state, "failed")
        self.assertIn("Zeitüberschreitung", emp.datev_job_error)
        fake_service.hr_exchange_job_status.assert_not_called()

    # ── _extract_job_errors helper ───────────────────────────────────────────
    def test_extract_job_errors_variants(self):
        Emp = self.env["hr.employee"]
        self.assertFalse(Emp._extract_job_errors({"errors": []}))
        self.assertEqual(Emp._extract_job_errors({"errors": [{"message": "Boom"}]}), "Boom")
        self.assertEqual(
            Emp._extract_job_errors({"errors": [{"code": "E1", "client_message": "Boom"}]}),
            "[E1] Boom",
        )
        # dict instead of list
        self.assertEqual(Emp._extract_job_errors({"errors": {"technical_message": "Kaputt"}}), "Kaputt")
        # plain strings
        self.assertEqual(Emp._extract_job_errors({"messages": ["a", "b"]}), "a\nb")
