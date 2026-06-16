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

    def test_get_authorization_url_contains_client_id(self):
        service = self._make_service()
        url = service.get_authorization_url()
        self.assertIn("test-client-id", url)
        self.assertIn("login.sandbox.datev.de", url)

    def test_get_authorization_url_contains_state(self):
        service = self._make_service()
        url = service.get_authorization_url()
        self.assertIn("state=", url)

    @patch("odoo.addons.datev_connector.services.datev_api.requests.post")
    def test_exchange_code_calls_token_endpoint(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.json.return_value = {
            "access_token": "acc",
            "refresh_token": "ref",
            "expires_in": 3600,
        }
        self.env["ir.config_parameter"].sudo().set_param(
            "datev_oauth_state", "validstate12345678901234"
        )
        service = self._make_service()
        result = service.exchange_code("authcode", "validstate12345678901234")
        self.assertEqual(result["access_token"], "acc")
        mock_post.assert_called_once()
