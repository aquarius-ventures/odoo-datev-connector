import base64
import hashlib
import logging
import secrets
import urllib.parse
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from odoo import SUPERUSER_ID
from odoo import api as odoo_api
from odoo.exceptions import UserError
from requests import Response

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
_ACCT_CLIENTS_BASE = {
    "prod": "https://accounting-clients.api.datev.de/platform/v2",
    "sandbox": "https://accounting-clients.api.datev.de/platform-sandbox/v2",
}
_DOCS_API_BASE = {
    "prod": "https://accounting-documents.api.datev.de/platform/v2",
    "sandbox": "https://accounting-documents.api.datev.de/platform-sandbox/v2",
}

# Request headers that must never appear in the technical log.
_REDACTED_HEADERS = ("authorization", "x-datev-client-secret")

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
    # HTTP choke point + technical log (DATEV MUST, P1.1)
    # ------------------------------------------------------------------

    def _http(
        self,
        method: str,
        url: str,
        *,
        headers=None,
        params=None,
        data=None,
        json=None,
        files=None,
        auth=None,
        timeout=60,
        log_body=False,
    ) -> Response:
        """Single choke point for ALL HTTP communication with the DATEV API
        gateway. Every request/response pair is written to datev.api.log.
        ``log_body=True`` stores the response body also for non-error responses
        (required for status queries)."""
        request_ts = datetime.utcnow()
        if params:
            full_url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        else:
            full_url = url
        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                data=data,
                json=json,
                files=files,
                auth=auth,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            self._log_api_call(method, full_url, headers, error=str(exc), request_ts=request_ts)
            raise
        try:
            logged_url = resp.request.url or full_url
        except Exception:
            logged_url = full_url
        self._log_api_call(
            method,
            logged_url,
            headers,
            resp=resp,
            request_ts=request_ts,
            response_ts=datetime.utcnow(),
            log_body=log_body,
        )
        return resp

    def _log_api_call(
        self, method, url, headers, resp=None, error=None, request_ts=None, response_ts=None, log_body=False
    ):
        """Write one datev.api.log row in its own transaction so log entries
        survive a rollback of the business transaction. Never raises."""
        try:
            redacted = {
                str(k): ("<redacted>" if str(k).lower() in _REDACTED_HEADERS else str(v))
                for k, v in (headers or {}).items()
            }
            vals = {
                "request_ts": request_ts or datetime.utcnow(),
                "method": str(method),
                "url": str(url)[:2000],
                "request_headers": "\n".join(f"{k}: {v}" for k, v in redacted.items()),
                "company_id": self._company_id,
            }
            if resp is not None:
                status_code = int(resp.status_code)
                vals.update(
                    {
                        "response_ts": response_ts or datetime.utcnow(),
                        "status_code": status_code,
                        "x_global_transaction_id": str(resp.headers.get("X-Global-Transaction-ID") or ""),
                        "v_cap_request_id": str(resp.headers.get("V-Cap-Request-ID") or ""),
                    }
                )
                if log_body or status_code >= 400:
                    vals["response_body"] = str(resp.text)[:8000]
            if error:
                vals["error"] = str(error)[:500]
            with self._env.registry.cursor() as cr:
                env = odoo_api.Environment(cr, SUPERUSER_ID, {})
                env["datev.api.log"].create(vals)
        except Exception:
            _logger.exception("DATEV: failed to write API log entry")

    @staticmethod
    def _format_http_error(resp) -> str:
        """Build a user-facing message from an error response.

        DATEV answers 4XX with RFC 9457 application/problem+json; title,
        detail and any contained help URLs must be shown to the user (MUST).
        Never includes tokens or secrets."""
        try:
            body = resp.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return (resp.text or "")[:500]
        parts = []
        title = body.get("title") or body.get("error")
        detail = body.get("detail") or body.get("error_description")
        if title:
            parts.append(str(title))
        if detail and detail != title:
            parts.append(str(detail))

        urls = set()

        def _collect_urls(node):
            if isinstance(node, dict):
                for value in node.values():
                    _collect_urls(value)
            elif isinstance(node, list):
                for value in node:
                    _collect_urls(value)
            elif isinstance(node, str) and node.startswith(("http://", "https://")):
                urls.add(node)

        _collect_urls(body)
        if urls:
            parts.append("Hilfe: " + " | ".join(sorted(urls)))
        return " — ".join(parts) if parts else str(body)[:500]

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
        scopes += company.datev_get_additional_scopes()
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
            resp = self._http(
                "POST",
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
                token_type_hint,
                resp.status_code,
                resp.text[:200],
            )
        return resp.ok

    def get_userinfo(self, access_token: str) -> dict:
        """Fetch the OIDC userinfo for the person who issued the token."""
        url = _OAUTH_BASE[self._env_key]["userinfo"]
        try:
            resp = self._http(
                "GET",
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
            resp = self._http(
                "POST",
                url,
                data=payload,
                auth=(self._client_id, self._client_secret),
                timeout=30,
            )
        except requests.RequestException as exc:
            raise UserError(f"DATEV token request failed: {exc}") from exc
        if not resp.ok:
            detail = self._format_http_error(resp)
            _logger.error("DATEV token error %s: %s", resp.status_code, detail)
            raise UserError(f"DATEV token request failed ({resp.status_code}): {detail}")
        data = resp.json()
        granted_scope = data.get("scope", "<not returned by DATEV>")
        _logger.info("DATEV token granted — scope: %s", granted_scope)
        return data

    # ------------------------------------------------------------------
    # Generic API calls
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        token = self._env["datev.token"].search([("company_id", "=", self._company_id)], limit=1)
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

    def post(
        self, path: str, json: Optional[Dict] = None, data: Any = None, headers: Optional[Dict] = None
    ) -> Response:
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
        log_body: bool = False,
    ) -> Response:
        try:
            resp = self._http(
                method,
                url,
                headers=self._headers(extra_headers),
                params=params,
                json=json,
                data=data,
                log_body=log_body,
            )
        except requests.RequestException as exc:
            raise UserError(f"DATEV connection error: {exc}") from exc
        if not resp.ok:
            detail = self._format_http_error(resp)
            _logger.error("DATEV API %s %s → %s: %s", method, url, resp.status_code, detail)
            if resp.status_code == 401:
                raise UserError(
                    "DATEV: Anmeldung ungültig oder abgelaufen — bitte neu mit " "DATEV verbinden. (%s)" % detail
                )
            raise UserError(f"DATEV API error {resp.status_code}: {detail}")
        return resp

    def extf_job_status(self, job_url: str) -> dict:
        """Poll the status of an async EXTF import job.

        Returns a dict with at minimum a '_result' key:
          'succeeded', 'failed', 'pending', or 'error'.
        On failure, '_errors' contains a list of error strings.
        """
        try:
            resp = self._http(
                "GET",
                job_url,
                headers={
                    "Authorization": f"Bearer {self._get_token()}",
                    "X-DATEV-Client-Id": self._client_id,
                    "Accept": "application/json;charset=utf-8",
                },
                timeout=30,
                log_body=True,  # status query: body must be logged
            )
            _logger.info("DATEV job status %s → %s: %s", job_url, resp.status_code, resp.text)
        except requests.RequestException as exc:
            _logger.warning("DATEV job status poll failed: %s", exc)
            return {"_result": "error", "_errors": [str(exc)]}

        if resp.status_code == 404:
            # A 404 on a known job URL is unusual — flag it in the log, but the
            # poll-timeout in the caller prevents endless pending states.
            _logger.warning(
                "DATEV EXTF job status 404 for %s — treated as pending " "(Auffälligkeit, siehe datev.api.log).",
                job_url,
            )
            return {"_result": "pending"}
        if resp.status_code == 202:
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
                error_strs = [f"{title}: {e.get('name', '')} – {e.get('reason', '')}" for e in affected]
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

    def hr_exchange_get_client(self, client_id: str) -> dict:
        """Authorization check (MUST): verify that the token grants access to
        the payroll client before any data transfer."""
        url = _HR_EXCHANGE_API_BASE[self._env_key] + f"/clients/{client_id}"
        resp = self._request("GET", url, extra_headers={"X-DATEV-Client-Id": self._client_id})
        return resp.json()

    def hr_exchange_create_fetch_job(
        self, client_id: str, reference_date: str, resource_name: str = "employees"
    ) -> dict:
        """Start an async read job (MUST: complete read before create/modify)."""
        url = _HR_EXCHANGE_API_BASE[self._env_key] + f"/clients/{client_id}/jobs"
        resp = self._request(
            "POST",
            url,
            json={"resource_name": resource_name, "reference_date": reference_date},
            extra_headers={"Target-System": "lodas", "X-DATEV-Client-Id": self._client_id},
        )
        return resp.json()

    def hr_exchange_job_result(self, client_id: str, job_uuid: str, resource: str = "employees") -> dict:
        """Fetch the result document of a finished job (MUST after every
        creation/modification: verify data persistence, evaluate errors[])."""
        url = _HR_EXCHANGE_API_BASE[self._env_key] + f"/clients/{client_id}/jobs/{job_uuid}/result/{resource}"
        resp = self._request("GET", url, extra_headers={"X-DATEV-Client-Id": self._client_id})
        return resp.json()

    def hr_exchange_post_employees(self, client_id: str, employees: list, reference_date: str) -> dict:
        """Create new employees in DATEV LODAS (async — returns 202 job)."""
        url = _HR_EXCHANGE_API_BASE[self._env_key] + f"/clients/{client_id}/employees"
        resp = self._request(
            "POST",
            url,
            params={"reference-date": reference_date},
            json=employees,
            extra_headers={"Target-System": "lodas", "X-DATEV-Client-Id": self._client_id},
        )
        return resp.json()

    def hr_exchange_put_employee(
        self, client_id: str, personnel_number: str, employee: dict, reference_date: str
    ) -> dict:
        """Update an existing employee in DATEV LODAS (async — returns 202 job)."""
        url = _HR_EXCHANGE_API_BASE[self._env_key] + f"/clients/{client_id}/employees/{personnel_number}"
        resp = self._request(
            "PUT",
            url,
            params={"reference-date": reference_date},
            json=employee,
            extra_headers={"Target-System": "lodas", "X-DATEV-Client-Id": self._client_id},
        )
        return resp.json()

    def hr_exchange_job_status(self, client_id: str, job_uuid: str) -> dict:
        """Poll the state of a hr:exchange async job."""
        url = _HR_EXCHANGE_API_BASE[self._env_key] + f"/clients/{client_id}/jobs/{job_uuid}"
        resp = self._request(
            "GET",
            url,
            extra_headers={"X-DATEV-Client-Id": self._client_id},
            log_body=True,  # status query: body must be logged
        )
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
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "X-DATEV-Client-Id": self._client_id,
            "X-DATEV-Client-Secret": self._client_secret,
            "Accept": "application/json;charset=utf-8",
            "Content-Type": "application/octet-stream",
            "Filename": filename,
            "Reference-Id": reference_id,
            "Client-Application-Version": "1.0",
        }
        _logger.info(
            "DATEV EXTF import → POST %s | Filename: %s | Reference-Id: %s | payload: %d bytes",
            url,
            filename,
            reference_id,
            len(csv_bytes),
        )
        try:
            resp = self._http("POST", url, headers=headers, data=csv_bytes, timeout=60)
        except requests.RequestException as exc:
            raise UserError(f"DATEV connection error: {exc}") from exc
        if not resp.ok:
            detail = self._format_http_error(resp)
            _logger.error("DATEV EXTF import FAILED %s → %s: %s", url, resp.status_code, detail)
            raise UserError(f"DATEV EXTF upload error {resp.status_code}: {detail}")
        return resp

    # ------------------------------------------------------------------
    # accounting:clients (Mandanten-/Berechtigungsprüfung)
    # ------------------------------------------------------------------

    def accounting_clients_list(self, top: int = 100, skip: int = 0) -> list:
        """List clients the token may access (paged, max 100 per page)."""
        url = _ACCT_CLIENTS_BASE[self._env_key] + "/clients"
        resp = self._request(
            "GET",
            url,
            params={"top": top, "skip": skip},
            extra_headers={"X-DATEV-Client-Id": self._client_id},
            log_body=True,
        )
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("data", data.get("clients", []))

    def accounting_clients_get(self, client_id: str) -> dict:
        """Authorization check for the Buchungsdatenservice (MUST before
        transfer): GET /clients/{consultant}-{client} incl. its services."""
        url = _ACCT_CLIENTS_BASE[self._env_key] + f"/clients/{client_id}"
        resp = self._request(
            "GET",
            url,
            extra_headers={"X-DATEV-Client-Id": self._client_id},
            log_body=True,
        )
        return resp.json()

    # ------------------------------------------------------------------
    # accounting:documents (Belegbilderservice)
    # ------------------------------------------------------------------

    def documents_get_client(self, client_id: str) -> dict:
        """Authorization check for the Belegbilderservice."""
        url = _DOCS_API_BASE[self._env_key] + f"/clients/{client_id}"
        resp = self._request(
            "GET",
            url,
            extra_headers={"X-DATEV-Client-Id": self._client_id},
            log_body=True,
        )
        return resp.json()

    def documents_upload(
        self, client_id: str, document_id: str, filename: str, file_bytes: bytes, metadata: dict
    ) -> Response:
        """Upload one voucher image (Belegbild) to DATEV Unternehmen online.

        PUT /clients/{client-id}/documents/{document-id} (multipart). The
        document GUID is generated by the caller and stored on the move, so a
        repeated export cannot create duplicate documents. ``metadata`` must
        contain either none or all three repository levels category/folder/
        register (DATEV MUST).
        """
        import json as json_lib

        url = _DOCS_API_BASE[self._env_key] + f"/clients/{client_id}/documents/{document_id}"
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "X-DATEV-Client-Id": self._client_id,
            "Accept": "application/json",
            # Content-Type is set by requests (multipart boundary).
        }
        files = {
            "file": (filename, file_bytes, "application/octet-stream"),
            "metadata": (None, json_lib.dumps(metadata), "application/json"),
        }
        try:
            resp = self._http("PUT", url, headers=headers, files=files, timeout=120)
        except requests.RequestException as exc:
            raise UserError(f"DATEV connection error: {exc}") from exc
        if not resp.ok:
            detail = self._format_http_error(resp)
            _logger.error("DATEV document upload FAILED %s → %s: %s", url, resp.status_code, detail)
            raise UserError(f"DATEV Belegbild-Upload fehlgeschlagen ({resp.status_code}): {detail}")
        return resp
