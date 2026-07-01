import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DatevOAuthController(http.Controller):

    _SETTINGS_URL = "/web#action=base_setup.action_general_configuration"

    @http.route("/web/datev/oauth/callback", type="http", auth="user", methods=["GET"])
    def oauth_callback(self, code=None, state=None, error=None, **kwargs):
        company = request.env.company

        if error:
            _logger.error("DATEV OAuth error: %s", error)
            company.sudo().datev_last_error = error
            return request.redirect(self._SETTINGS_URL)

        if not code:
            return request.redirect(self._SETTINGS_URL)

        config = request.env["res.config.settings"]._get_datev_config(company)
        from ..services.datev_api import DatevApiService

        service = DatevApiService(request.env, config)
        try:
            token_data = service.exchange_code(code, state)
        except Exception as exc:
            _logger.exception("DATEV code exchange failed")
            company.sudo().datev_last_error = str(exc)[:500]
            return request.redirect(self._SETTINGS_URL)

        token = request.env["datev.token"]._get_or_create(company.id)
        token.sudo()._store_token_data(token_data)
        company.sudo().datev_last_error = False

        return request.redirect(self._SETTINGS_URL + "&datev_connected=1")
