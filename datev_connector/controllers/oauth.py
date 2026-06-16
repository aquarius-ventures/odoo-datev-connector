import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DatevOAuthController(http.Controller):

    @http.route("/web/datev/oauth/callback", type="http", auth="user", methods=["GET"])
    def oauth_callback(self, code=None, state=None, error=None, **kwargs):
        if error:
            _logger.error("DATEV OAuth error: %s", error)
            return request.redirect(
                "/web#action=base_setup.action_general_configuration"
                f"&datev_error={error}"
            )

        if not code:
            return request.redirect("/web#action=base_setup.action_general_configuration")

        config = request.env["res.config.settings"]._get_datev_config()
        from ..services.datev_api import DatevApiService

        service = DatevApiService(request.env, config)
        try:
            token_data = service.exchange_code(code, state)
        except Exception as exc:
            _logger.exception("DATEV code exchange failed")
            return request.redirect(
                "/web#action=base_setup.action_general_configuration"
                f"&datev_error={exc}"
            )

        token = request.env["datev.token"]._get_or_create()
        token.sudo()._store_token_data(token_data)

        return request.redirect(
            "/web#action=base_setup.action_general_configuration&datev_connected=1"
        )
