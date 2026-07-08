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
        "revoke": "https://api.datev.de/revoke",
        "userinfo": "https://api.datev.de/userinfo",
    },
    "sandbox": {
        "auth": "https://login.datev.de/openidsandbox/authorize",
        "token": "https://sandbox-api.datev.de/token",
        "revoke": "https://sandbox-api.datev.de/revoke",
        "userinfo": "https://sandbox-api.datev.de/userinfo",
    },
}

# DATEV REST API base URLs (per-product — each lives on its own subdomain)
_API_BASE = {
    "prod": "https://api.datev.de/platform/v1",
    "sandbox": "https://api.datev.de/platform-sandbox/v1",
}
_EXTF_API_BASE = {
    "prod": "https://accounting-extf-files.api.datev.de/platform/v3",
    "sandbox": "https://accounting-extf-files.api.datev.de/platform-sandbox/v3",
}
_HR_EXCHANGE_API_BASE = {
    "prod": "https://hr-exchange.api.datev.de/platform/v1",
    "sandbox": "https://hr-exchange.api.datev.de/platform-sandbox/v1",
}

_OAUTH_CALLBACK_PATH = "/web/datev/oauth/callback"


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
        # Company whose DATEV token should be used (per-company connections).
        self._company_id = config.get("company_id") or env.company.id

    # ------------------------------------------------------------------
    # OAuth2 + PKCE helpers
    # ------------------------------------------------------------------

    def _get_base_url(self) -> str:
        return self._env["ir.config_parameter"].sudo().get_param("web.base.url", "")

    def get_scope(self) -> str:
        """Scope string limited to the DATEV data services actually in use
        (MUST: only request scopes the customer needs)."""
        scopes = ["openid", "profile"]
        company = self._env["res.company"].sudo().browse(self._company_id)
        if company.datev_get_service_accounting():
            scopes += ["datev:accounting:extf-files-import", "datev:accounting:clients"]
        if company.datev_get_service_hr():
            scopes.append("datev:hr:payrolldataexchange")
        return " ".join(scopes)

    def get_authorization_url(self) -> str:
        # state and nonce: DATEV requires >= 20 chars each, new per request.
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier, challenge = _pkce_pair()
        self._env["datev.oauth.flow"]._begin(state, nonce, verifier, self._company_id)
        redirect_uri = self._get_base_url() + _OAUTH_CALLBACK_PATH
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": self.get_scope(),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Recommended by the DATEV auth guide (Windows SSO with DATEV login).
            "enableWindowsSso": "true",
        }
        return _OAUTH_BASE[self._env_key]["auth"] + "?" + urllib.parse.urlencode(params)

    def exchange_code(self, code: str, code_verifier: str, nonce: str = "") -> dict:
        """Redeem an authorization code. State validation and PKCE-verifier
        lookup happen in the caller via datev.oauth.flow (single-use)."""
        redirect_uri = self._get_base_url() + _OAUTH_CALLBACK_PATH
        result = self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        if nonce:
            self._verify_id_token_nonce(result, nonce)
        return result

    @staticmethod
    def _verify_id_token_nonce(token_data: dict, expected_nonce: str):
        """Check the nonce claim of the ID token against the flow's nonce.

        The payload is decoded without signature verification — this is only
        the replay-protection check recommended by the DATEV auth guide, the
        token itself was received over TLS directly from DATEV.
        """
        id_token = token_data.get("id_token")
        if not id_token:
            return
        try:
            import json
            payload_b64 = id_token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        except Exception:
            _logger.warning("DATEV OAuth: could not decode ID token payload.")
            return
        claim_nonce = claims.get("nonce")
        if claim_nonce and not secrets.compare_digest(claim_nonce, expected_nonce):
            raise UserError("DATEV OAuth2: ID token nonce mismatch. Please restart the flow.")

    def exchange_refresh_token(self, refresh_token: str) -> dict:
        return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def revoke_token(self, token: str, token_type_hint: str) -> bool:
        """Revoke an access or refresh token at DATEV (RFC 7009).

        ``token_type_hint`` ('access_token' | 'refresh_token') is mandatory at
        DATEV. Returns True when DATEV confirmed the revocation; failures are
        logged but never raise — a disconnect must always go through locally.
        """
        url = _OAUTH_BASE[self._env_key]["revoke"]
        try:
            resp = requests.post(
                url,
                data={"token": token, "token_type_hint": token_type_hint},
                auth=(self._client_id, self._client_secret),
                timeout=30,
            )
        except requests.RequestException as exc:
            _logger.warning("DATEV revoke (%s) failed: %s", token_type_hint, exc)
            return False
        if not resp.ok:
            _logger.warning(
                "DATEV revoke (%s) returned %s: %s",
                token_type_hint, resp.status_code, resp.text[:200],
            )
        return resp.ok

    def get_userinfo(self, access_token: str) -> dict:
        """Fetch the OIDC userinfo for the person who issued the token."""
        url = _OAUTH_BASE[self._env_key]["userinfo"]
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                timeout=30,
            )
            if resp.ok:
                return resp.json()
            _logger.warning("DATEV userinfo returned %s: %s", resp.status_code, resp.text[:200])
        except requests.RequestException as exc:
            _logger.warning("DATEV userinfo failed: %s", exc)
        return {}

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
        except requests.RequestException as exc:
            raise UserError(f"DATEV token request failed: {exc}") from exc
        if not resp.ok:
            _logger.error("DATEV token error %s: %s", resp.status_code, resp.text)
            detail = resp.text
            try:
                body = resp.json()
                detail = body.get("error_description") or body.get("error") or detail
            except Exception:
                pass
            raise UserError(
                f"DATEV token request failed ({resp.status_code}): {detail}"
            )
        data = resp.json()
        granted_scope = data.get("scope", "<not returned by DATEV>")
        _logger.info("DATEV token granted — scope: %s", granted_scope)
        return data

    # ------------------------------------------------------------------
    # Generic API calls
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        token = self._env["datev.token"].search(
            [("company_id", "=", self._company_id)], limit=1
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

    def extf_job_status(self, job_url: str) -> dict:
        """Poll the status of an async EXTF import job.

        Returns a dict with at minimum a '_result' key:
          'succeeded', 'failed', 'pending', or 'error'.
        On failure, '_errors' contains a list of error strings.
        """
        try:
            resp = requests.get(
                job_url,
                headers={
                    "Authorization": f"Bearer {self._get_token()}",
                    "X-DATEV-Client-Id": self._client_id,
                    "Accept": "application/json;charset=utf-8",
                },
                timeout=30,
            )
            _logger.info("DATEV job status %s → %s: %s", job_url, resp.status_code, resp.text)
        except requests.RequestException as exc:
            _logger.warning("DATEV job status poll failed: %s", exc)
            return {"_result": "error", "_errors": [str(exc)]}

        if resp.status_code in (202, 404):
            return {"_result": "pending"}
        if not resp.ok:
            return {"_result": "error", "_errors": [f"HTTP {resp.status_code}: {resp.text[:200]}"]}

        try:
            data = resp.json()
        except Exception:
            return {"_result": "error", "_errors": [resp.text[:200]]}

        result_val = (data.get("result") or "").lower()
        if result_val in ("success", "succeeded"):
            return {"_result": "succeeded", **data}

        errors = data.get("errors") or data.get("messages") or []
        if isinstance(errors, list):
            error_strs = [e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in errors]
        else:
            error_strs = [str(errors)]

        if not error_strs:
            validation = data.get("validation_details") or {}
            title = validation.get("title", "")
            detail = validation.get("detail", "")
            affected = validation.get("affected_elements") or []
            if affected:
                error_strs = [
                    f"{title}: {e.get('name', '')} – {e.get('reason', '')}"
                    for e in affected
                ]
            elif title or detail:
                error_strs = [f"{title}: {detail}".strip(": ")]

        # Only mark as failed when DATEV explicitly signals failure or returns error details.
        # Any unknown/in-progress result value (e.g. "processing") stays pending.
        _FAILURE_RESULTS = {"error", "failed", "rejected", "invalid"}
        if result_val in _FAILURE_RESULTS or error_strs:
            return {"_result": "failed", "_errors": error_strs, **data}

        return {"_result": "pending"}

    # ------------------------------------------------------------------
    # HR Exchange (Personalstammdaten)
    # ------------------------------------------------------------------

    def hr_exchange_post_employees(self, client_id: str, employees: list, reference_date: str) -> dict:
        """Create new employees in DATEV LODAS (async — returns 202 job)."""
        url = _HR_EXCHANGE_API_BASE[self._env_key] + f"/clients/{client_id}/employees"
        resp = self._request(
            "POST", url,
            params={"reference-date": reference_date},
            json=employees,
            extra_headers={"Target-System": "lodas", "X-DATEV-Client-Id": self._client_id},
        )
        return resp.json()

    def hr_exchange_put_employee(self, client_id: str, personnel_number: str, employee: dict, reference_date: str) -> dict:
        """Update an existing employee in DATEV LODAS (async — returns 202 job)."""
        url = _HR_EXCHANGE_API_BASE[self._env_key] + f"/clients/{client_id}/employees/{personnel_number}"
        resp = self._request(
            "PUT", url,
            params={"reference-date": reference_date},
            json=employee,
            extra_headers={"Target-System": "lodas", "X-DATEV-Client-Id": self._client_id},
        )
        return resp.json()

    def hr_exchange_job_status(self, client_id: str, job_uuid: str) -> dict:
        """Poll the state of a hr:exchange async job."""
        url = _HR_EXCHANGE_API_BASE[self._env_key] + f"/clients/{client_id}/jobs/{job_uuid}"
        resp = self._request("GET", url, extra_headers={"X-DATEV-Client-Id": self._client_id})
        return resp.json()

    # ------------------------------------------------------------------
    # EXTF file upload + job status
    # ------------------------------------------------------------------

    def extf_import(self, client_id: str, filename: str, csv_bytes: bytes, reference_id: str = "") -> "Response":
        """Upload an EXTF Buchungsstapel CSV to DATEV (async — returns 202)."""
        url = _EXTF_API_BASE[self._env_key] + f"/clients/{client_id}/extf-files/import"
        if not reference_id:
            import uuid
            reference_id = str(uuid.uuid4())
        request_headers = {
            "Authorization": "Bearer <token>",
            "X-DATEV-Client-Id": self._client_id,
            "X-DATEV-Client-Secret": "<secret>",
            "Accept": "application/json;charset=utf-8",
            "Content-Type": "application/octet-stream",
            "Filename": filename,
            "Reference-Id": reference_id,
            "Client-Application-Version": "1.0",
        }
        first_line = csv_bytes.split(b"\n")[0].decode("utf-8", errors="replace")
        _logger.info(
            "DATEV EXTF import → POST %s | Filename: %s | Reference-Id: %s | payload: %d bytes | first_line: %r",
            url, filename, reference_id, len(csv_bytes), first_line,
        )
        token = self._get_token()
        try:
            resp = requests.post(
                url,
                data=csv_bytes,
                headers={
                    **request_headers,
                    "Authorization": f"Bearer {token}",
                    "X-DATEV-Client-Secret": self._client_secret,
                },
                timeout=60,
            )
            _logger.info(
                "DATEV EXTF import response: %s | headers: %s | body: %s",
                resp.status_code, dict(resp.headers), resp.text[:500],
            )
            if not resp.ok:
                _logger.error("DATEV EXTF import FAILED %s → %s: %s", url, resp.status_code, resp.text)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as exc:
            body = ""
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text
            raise UserError(f"DATEV EXTF upload error {exc.response.status_code}: {body}") from exc
        except requests.RequestException as exc:
            raise UserError(f"DATEV connection error: {exc}") from exc
