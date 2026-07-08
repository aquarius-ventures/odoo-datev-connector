import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DatevOAuthController(http.Controller):

    _SETTINGS_URL = "/web#action=base_setup.action_general_configuration"

    @http.route("/web/datev/oauth/callback", type="http", auth="user", methods=["GET"])
    def oauth_callback(self, code=None, state=None, error=None, **kwargs):
        # Resolve the flow FIRST: it tells us which company the authorization
        # was started for (request.env.company is not reliable here) and makes
        # the state single-use.
        flow = request.env["datev.oauth.flow"]._consume(state)

        if error:
            _logger.error("DATEV OAuth error: %s", error)
            if flow:
                company = request.env["res.company"].sudo().browse(flow["company_id"])
                company.datev_last_error = error
            return request.redirect(self._SETTINGS_URL)

        if not code:
            return request.redirect(self._SETTINGS_URL)

        if not flow:
            _logger.warning("DATEV OAuth callback with unknown/expired state.")
            return request.redirect(self._SETTINGS_URL)

        company = request.env["res.company"].sudo().browse(flow["company_id"])
        config = request.env["res.config.settings"]._get_datev_config(company)
        from ..services.datev_api import DatevApiService

        service = DatevApiService(request.env, config)
        try:
            token_data = service.exchange_code(code, flow["code_verifier"], flow["nonce"])
        except Exception as exc:
            _logger.exception("DATEV code exchange failed")
            company.datev_last_error = str(exc)[:500]
            return request.redirect(self._SETTINGS_URL)

        # sudo: the connecting user is not necessarily in base.group_system,
        # but the token record itself must never be user-writable directly.
        token = request.env["datev.token"].sudo()._get_or_create(company.id)
        token._store_token_data(token_data)
        token._update_issuer_info(service, token_data)
        company.datev_last_error = False

        return request.redirect(self._SETTINGS_URL + "&datev_connected=1")
