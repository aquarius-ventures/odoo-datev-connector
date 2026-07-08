from odoo.tests.common import HttpCase


class TestDatevOAuthController(HttpCase):
    def test_callback_without_code_redirects(self):
        resp = self.url_open("/web/datev/oauth/callback", timeout=10)
        self.assertIn(resp.status_code, [200, 302, 303])

    def test_callback_with_error_redirects(self):
        resp = self.url_open("/web/datev/oauth/callback?error=access_denied", timeout=10)
        self.assertIn(resp.status_code, [200, 302, 303])
