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

    @patch("odoo.addons.datev_connector.services.datev_api.requests.post")
    def test_exchange_code_calls_token_endpoint(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, ok=True,
            json=MagicMock(return_value={
                "access_token": "acc",
                "refresh_token": "ref",
                "expires_in": 3600,
            }),
        )
        service = self._make_service()
        result = service.exchange_code("authcode", "test-verifier")
        self.assertEqual(result["access_token"], "acc")
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"]["code_verifier"], "test-verifier")
        self.assertEqual(kwargs["auth"], ("test-client-id", "test-client-secret"))

    @patch("odoo.addons.datev_connector.services.datev_api.requests.post")
    def test_revoke_token_sends_hint(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, ok=True)
        service = self._make_service()
        self.assertTrue(service.revoke_token("some-token", "refresh_token"))
        args, kwargs = mock_post.call_args
        self.assertIn("revoke", args[0])
        self.assertEqual(kwargs["data"]["token_type_hint"], "refresh_token")
        self.assertEqual(kwargs["data"]["token"], "some-token")

    def test_scope_respects_service_selection(self):
        company = self.env.company
        company.datev_service_accounting = False
        company.datev_service_hr = False
        service = self._make_service()
        self.assertEqual(service.get_scope(), "openid profile")
