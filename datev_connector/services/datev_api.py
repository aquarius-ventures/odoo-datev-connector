import logging
import secrets
import urllib.parse
from typing import Any

import requests
from requests import Response

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# DATEV OpenID Connect endpoints
_OAUTH_BASE = {
    "prod": {
        "auth": "https://login.datev.de/openid/authorize",
        "token": "https://login.datev.de/openid/token",
    },
    "sandbox": {
        "auth": "https://login.sandbox.datev.de/openid/authorize",
        "token": "https://login.sandbox.datev.de/openid/token",
    },
}

# DATEV REST API base URLs
_API_BASE = {
    "prod": "https://api.datev.de/platform/v1",
    "sandbox": "https://api.datev.de/platform-sandbox/v1",
}

_OAUTH_CALLBACK_PATH = "/web/datev/oauth/callback"
_STATE_PARAM_KEY = "datev_oauth_state"
_SCOPE = "openid profile datev:accounting:extf-files:read datev:accounting:extf-files:write"


class DatevApiService:
    """Low-level HTTP client for the DATEV Cloud REST API."""

    def __init__(self, env, config: dict):
        self._env = env
        self._client_id = config["client_id"]
        self._client_secret = config["client_secret"]
        self._env_key = "sandbox" if config.get("sandbox") else "prod"

    # ------------------------------------------------------------------
    # OAuth2 helpers
    # ------------------------------------------------------------------

    def _get_base_url(self) -> str:
        return self._env["ir.config_parameter"].sudo().get_param("web.base.url", "")

    def get_authorization_url(self) -> str:
        state = secrets.token_urlsafe(24)
        self._env["ir.config_parameter"].sudo().set_param(_STATE_PARAM_KEY, state)
        redirect_uri = self._get_base_url() + _OAUTH_CALLBACK_PATH
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": _SCOPE,
            "state": state,
        }
        return _OAUTH_BASE[self._env_key]["auth"] + "?" + urllib.parse.urlencode(params)

    def exchange_code(self, code: str, state: str) -> dict:
        expected_state = self._env["ir.config_parameter"].sudo().get_param(_STATE_PARAM_KEY)
        if not secrets.compare_digest(state or "", expected_state or ""):
            raise UserError("DATEV OAuth2: Invalid state parameter.")
        redirect_uri = self._get_base_url() + _OAUTH_CALLBACK_PATH
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        )

    def exchange_refresh_token(self, refresh_token: str) -> dict:
        return self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        )

    def _token_request(self, payload: dict) -> dict:
        url = _OAUTH_BASE[self._env_key]["token"]
        try:
            resp = requests.post(url, data=payload, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise UserError(f"DATEV token request failed: {exc}") from exc
        return resp.json()

    # ------------------------------------------------------------------
    # Generic API calls
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        token = self._env["datev.token"].search(
            [("company_id", "=", self._env.company.id)], limit=1
        )
        if not token:
            raise UserError("DATEV: Not connected. Please authenticate first.")
        return token.get_valid_access_token()

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def get(self, path: str, params: dict | None = None) -> Any:
        url = _API_BASE[self._env_key] + path
        resp = self._request("GET", url, params=params)
        return resp.json()

    def post(self, path: str, json: dict | None = None, data: Any = None, headers: dict | None = None) -> Response:
        url = _API_BASE[self._env_key] + path
        return self._request("POST", url, json=json, data=data, extra_headers=headers)

    def _request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        json: dict | None = None,
        data: Any = None,
        extra_headers: dict | None = None,
    ) -> Response:
        try:
            resp = requests.request(
                method,
                url,
                headers=self._headers(extra_headers),
                params=params,
                json=json,
                data=data,
                timeout=60,
            )
            resp.raise_for_status()
            return resp
        except requests.HTTPError as exc:
            body = ""
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text
            _logger.error("DATEV API %s %s → %s: %s", method, url, exc.response.status_code, body)
            raise UserError(f"DATEV API error {exc.response.status_code}: {body}") from exc
        except requests.RequestException as exc:
            raise UserError(f"DATEV connection error: {exc}") from exc
