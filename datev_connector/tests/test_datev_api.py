import urllib.parse
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


class TestDatevApiService(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = {
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "sandbox": True,
        }

    def _make_service(self):
        from odoo.addons.datev_connector.services.datev_api import DatevApiService

        return DatevApiService(self.env, self.config)

    def _parse_qs(self, url):
        return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}

    def test_authorization_url_parameters(self):
        service = self._make_service()
        url = service.get_authorization_url()
        self.assertIn("login.datev.de/openidsandbox/authorize", url)
        params = self._parse_qs(url)
        self.assertEqual(params["client_id"], "test-client-id")
        self.assertEqual(params["code_challenge_method"], "S256")
        self.assertEqual(params["enableWindowsSso"], "true")
        # DATEV requires state and nonce with >= 20 characters
        self.assertGreaterEqual(len(params["state"]), 20)
        self.assertGreaterEqual(len(params["nonce"]), 20)
        self.assertTrue(params["scope"].startswith("openid profile"))

    def test_state_and_nonce_fresh_per_request(self):
        service = self._make_service()
        p1 = self._parse_qs(service.get_authorization_url())
        p2 = self._parse_qs(service.get_authorization_url())
        self.assertNotEqual(p1["state"], p2["state"])
        self.assertNotEqual(p1["nonce"], p2["nonce"])
        self.assertNotEqual(p1["code_challenge"], p2["code_challenge"])

    def test_oauth_flow_is_single_use(self):
        service = self._make_service()
        params = self._parse_qs(service.get_authorization_url())
        Flow = self.env["datev.oauth.flow"]
        flow = Flow._consume(params["state"])
        self.assertTrue(flow)
        self.assertEqual(flow["company_id"], self.env.company.id)
        self.assertGreaterEqual(len(flow["nonce"]), 20)
        self.assertTrue(flow["code_verifier"])
        # second consume must fail (single-use)
        self.assertIsNone(Flow._consume(params["state"]))
        self.assertIsNone(Flow._consume("unknown-state-1234567890"))

    @staticmethod
    def _mock_response(status_code=200, json_data=None, headers=None, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.ok = status_code < 400
        resp.headers = headers or {}
        resp.text = text
        resp.json.return_value = json_data or {}
        resp.request.url = "https://mocked.example/url"
        return resp

    @patch("odoo.addons.datev_connector.services.datev_api.requests.request")
    def test_exchange_code_calls_token_endpoint(self, mock_request):
        mock_request.return_value = self._mock_response(
            json_data={
                "access_token": "acc",
                "refresh_token": "ref",
                "expires_in": 3600,
            }
        )
        service = self._make_service()
        result = service.exchange_code("authcode", "test-verifier")
        self.assertEqual(result["access_token"], "acc")
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(kwargs["data"]["code_verifier"], "test-verifier")
        self.assertEqual(kwargs["auth"], ("test-client-id", "test-client-secret"))

    @patch("odoo.addons.datev_connector.services.datev_api.requests.request")
    def test_revoke_token_sends_hint(self, mock_request):
        mock_request.return_value = self._mock_response()
        service = self._make_service()
        self.assertTrue(service.revoke_token("some-token", "refresh_token"))
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("revoke", args[1])
        self.assertEqual(kwargs["data"]["token_type_hint"], "refresh_token")
        self.assertEqual(kwargs["data"]["token"], "some-token")

    @patch("odoo.addons.datev_connector.services.datev_api.requests.request")
    def test_http_writes_redacted_log(self, mock_request):
        mock_request.return_value = self._mock_response(
            headers={
                "X-Global-Transaction-ID": "gtid-1",
                "V-Cap-Request-ID": "vcap-1",
            },
        )
        service = self._make_service()
        service._http(
            "GET",
            "https://api.datev.de/test",
            headers={"Authorization": "Bearer SECRET-TOKEN", "Accept": "application/json"},
        )
        # The log entry is committed in its own transaction (so it survives
        # business rollbacks) — it is therefore invisible to this test's
        # repeatable-read snapshot and must be checked via a fresh cursor.
        from odoo import SUPERUSER_ID, api

        with self.env.registry.cursor() as cr:
            env2 = api.Environment(cr, SUPERUSER_ID, {})
            logs = env2["datev.api.log"].search([("url", "like", "api.datev.de/test")], order="id desc", limit=1)
            self.assertTrue(logs, "no datev.api.log entry was written")
            self.assertEqual(logs.method, "GET")
            self.assertEqual(logs.x_global_transaction_id, "gtid-1")
            self.assertEqual(logs.v_cap_request_id, "vcap-1")
            self.assertNotIn("SECRET-TOKEN", logs.request_headers)
            self.assertIn("<redacted>", logs.request_headers)
            # 200 without log_body: response body must NOT be stored
            self.assertFalse(logs.response_body)
            # clean up the committed row so the test leaves no trace
            logs.unlink()

    @patch("odoo.addons.datev_connector.services.datev_api.requests.request")
    def test_4xx_error_shows_problem_json_details(self, mock_request):
        from odoo.exceptions import UserError

        mock_request.return_value = self._mock_response(
            status_code=403,
            json_data={
                "title": "Forbidden",
                "detail": "Dem Mandanten fehlt der Buchungsdatenservice.",
                "instance": "https://apps.datev.de/help-center/xyz",
            },
        )
        from datetime import datetime, timedelta

        self.env["datev.token"].create(
            {
                "company_id": self.env.company.id,
                "access_token": "test-at",
                "token_expiry": datetime.utcnow() + timedelta(hours=1),
                "state": "connected",
            }
        )
        service = self._make_service()
        with self.assertRaises(UserError) as ctx:
            service._request("GET", "https://api.datev.de/test", extra_headers={})
        msg = str(ctx.exception)
        self.assertIn("Forbidden", msg)
        self.assertIn("Buchungsdatenservice", msg)
        self.assertIn("https://apps.datev.de/help-center/xyz", msg)

    def test_scope_respects_service_selection(self):
        company = self.env.company
        company.datev_service_accounting = False
        company.datev_service_hr = False
        service = self._make_service()
        self.assertEqual(service.get_scope(), "openid profile")
