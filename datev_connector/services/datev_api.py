import base64
import hashlib
import logging
import secrets
import urllib.parse
from typing import Any, Dict, Optional

import requests
from requests import Response

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# DATEV OpenID Connect endpoints
# Both environments use login.datev.de — only the path differs.
# Discovery: https://login.datev.de/openid/.well-known/openid-configuration
_OAUTH_BASE = {
    "prod": {
        "auth": "https://login.datev.de/openid/authorize",
        "token": "https://api.datev.de/token",
    },
    "sandbox": {
        "auth": "https://login.datev.de/openidsandbox/authorize",
        "token": "https://sandbox-api.datev.de/token",
    },
}

# DATEV REST API base URLs
_API_BASE = {
    "prod": "https://api.datev.de/platform/v1",
    "sandbox": "https://api.datev.de/platform-sandbox/v1",
}

_OAUTH_CALLBACK_PATH = "/web/datev/oauth/callback"
_STATE_PARAM_KEY = "datev_oauth_state"
_PKCE_VERIFIER_KEY = "datev_oauth_pkce_verifier"
_SCOPE = (
    "openid profile "
    "datev:accounting:extf-files:read "
    "datev:accounting:extf-files:write "
    "datev:accounting:clients"
)


def _pkce_pair():
    """Generate a PKCE code_verifier and code_challenge (S256 method)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class DatevApiService:
    """Low-level HTTP client for the DATEV Cloud REST API."""

    def __init__(self, env, config: dict):
        self._env = env
        self._client_id = config["client_id"]
        self._client_secret = config["client_secret"]
        self._env_key = "sandbox" if config.get("sandbox") else "prod"

    # ------------------------------------------------------------------
    # OAuth2 + PKCE helpers
    # ------------------------------------------------------------------

    def _get_base_url(self) -> str:
        return self._env["ir.config_parameter"].sudo().get_param("web.base.url", "")

    def get_authorization_url(self) -> str:
        state = secrets.token_urlsafe(24)
        verifier, challenge = _pkce_pair()
        ICP = self._env["ir.config_parameter"].sudo()
        ICP.set_param(_STATE_PARAM_KEY, state)
        ICP.set_param(_PKCE_VERIFIER_KEY, verifier)
        redirect_uri = self._get_base_url() + _OAUTH_CALLBACK_PATH
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": _SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return _OAUTH_BASE[self._env_key]["auth"] + "?" + urllib.parse.urlencode(params)

    def exchange_code(self, code: str, state: str) -> dict:
        ICP = self._env["ir.config_parameter"].sudo()
        expected_state = ICP.get_param(_STATE_PARAM_KEY)
        if not secrets.compare_digest(state or "", expected_state or ""):
            raise UserError("DATEV OAuth2: Invalid state parameter.")
        verifier = ICP.get_param(_PKCE_VERIFIER_KEY)
        if not verifier:
            raise UserError("DATEV OAuth2: PKCE verifier missing. Please restart the OAuth flow.")
        redirect_uri = self._get_base_url() + _OAUTH_CALLBACK_PATH
        result = self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            }
        )
        ICP.set_param(_PKCE_VERIFIER_KEY, "")
        return result

    def exchange_refresh_token(self, refresh_token: str) -> dict:
        return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def _token_request(self, payload: dict) -> dict:
        # DATEV requires client_secret_basic: credentials via HTTP Basic Auth,
        # not in the POST body (client_secret_post).
        url = _OAUTH_BASE[self._env_key]["token"]
        try:
            resp = requests.post(
                url,
                data=payload,
                auth=(self._client_id, self._client_secret),
                timeout=30,
            )
            if not resp.ok:
                _logger.error("DATEV token error %s: %s", resp.status_code, resp.text)
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

    def _headers(self, extra: Optional[Dict] = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def get(self, path: str, params: Optional[Dict] = None) -> Any:
        url = _API_BASE[self._env_key] + path
        resp = self._request("GET", url, params=params)
        return resp.json()

    def post(self, path: str, json: Optional[Dict] = None, data: Any = None, headers: Optional[Dict] = None) -> Response:
        url = _API_BASE[self._env_key] + path
        return self._request("POST", url, json=json, data=data, extra_headers=headers)

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        json: Optional[Dict] = None,
        data: Any = None,
        extra_headers: Optional[Dict] = None,
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
