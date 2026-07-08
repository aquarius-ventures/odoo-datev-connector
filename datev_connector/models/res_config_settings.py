import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Per-company DATEV settings (stored on res.company).
    datev_client_id = fields.Char(
        related="company_id.datev_client_id",
        readonly=False,
        groups="base.group_system",
    )
    datev_client_secret = fields.Char(
        related="company_id.datev_client_secret",
        readonly=False,
        groups="base.group_system",
    )
    datev_mode = fields.Selection(
        related="company_id.datev_mode",
        readonly=False,
    )
    datev_consultant_number = fields.Char(
        related="company_id.datev_consultant_number",
        readonly=False,
    )
    datev_client_number = fields.Char(
        related="company_id.datev_client_number",
        readonly=False,
    )
    datev_account_number_length = fields.Selection(
        related="company_id.datev_account_number_length",
        readonly=False,
    )
    datev_last_error = fields.Char(
        related="company_id.datev_last_error",
        readonly=True,
    )
    datev_service_accounting = fields.Boolean(
        related="company_id.datev_service_accounting",
        readonly=False,
    )
    datev_service_hr = fields.Boolean(
        related="company_id.datev_service_hr",
        readonly=False,
    )
    datev_connection_state = fields.Selection(
        [
            ("disconnected", "Disconnected"),
            ("connected_unverified", "Verbunden — Mandant ungeprüft"),
            ("connected", "Connected"),
        ],
        string="Connection Status",
        compute="_compute_datev_connection_state",
    )
    datev_client_verified = fields.Boolean(
        related="company_id.datev_client_verified",
    )
    datev_client_check_info = fields.Char(
        related="company_id.datev_client_check_info",
    )
    # Mandatory connection details (DATEV MUST): RT expiry, issuer name,
    # granted scopes.
    datev_refresh_token_expiry = fields.Datetime(
        string="Refresh-Token gültig bis",
        compute="_compute_datev_token_info",
    )
    datev_issued_by_name = fields.Char(
        string="Verbunden durch",
        compute="_compute_datev_token_info",
    )
    datev_granted_scopes = fields.Char(
        string="Gewährte Scopes",
        compute="_compute_datev_token_info",
    )

    datev_redirect_uri = fields.Char(
        string="OAuth Redirect-URL",
        compute="_compute_datev_redirect_uri",
        help="Diese URL muss im DATEV Developer Portal exakt so als " "Redirect-URL der App registriert sein.",
    )

    def _compute_datev_redirect_uri(self):
        from ..services.datev_api import _OAUTH_CALLBACK_PATH

        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for rec in self:
            rec.datev_redirect_uri = base_url + _OAUTH_CALLBACK_PATH

    @api.model
    def _datev_check_redirect_url(self, sandbox):
        """Enforce the DATEV redirect-URL guidelines for confidential clients
        in production: HTTPS only, no localhost, no raw IPs, no custom schemes.
        Apps with non-compliant redirect URLs are blocked by DATEV from
        2026-03-01 on."""
        import ipaddress
        import urllib.parse as up

        if sandbox:
            return
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        parsed = up.urlparse(base_url)
        host = parsed.hostname or ""
        is_ip = False
        try:
            ipaddress.ip_address(host)
            is_ip = True
        except ValueError:
            pass
        if parsed.scheme != "https" or host in ("localhost", "127.0.0.1") or is_ip:
            raise UserError(
                _(
                    "DATEV Produktivbetrieb: Die Redirect-URL muss HTTPS sein und darf "
                    "weder localhost noch eine IP-Adresse enthalten (aktuelle Basis-URL: %s). "
                    "Apps mit unzulässigen Redirect-URLs werden von DATEV seit 01.03.2026 "
                    "gesperrt. Bitte 'web.base.url' auf die öffentliche HTTPS-Domain stellen."
                )
                % (base_url or "<leer>")
            )

    @api.depends("company_id", "datev_client_id", "datev_mode")
    def _compute_datev_connection_state(self):
        for rec in self:
            token = self.env["datev.token"].search([("company_id", "=", rec.company_id.id)], limit=1)
            if rec.company_id.datev_mode == "off" or not token or token.state != "connected":
                rec.datev_connection_state = "disconnected"
            elif not rec.company_id.datev_client_verified:
                # Token vorhanden, aber Berechtigungs-/Mandantenprüfung steht
                # aus — erst nach bestätigtem Check ist die Verbindung "grün".
                rec.datev_connection_state = "connected_unverified"
            else:
                rec.datev_connection_state = "connected"

    @api.depends("company_id")
    def _compute_datev_token_info(self):
        for rec in self:
            token = self.env["datev.token"].search([("company_id", "=", rec.company_id.id)], limit=1)
            rec.datev_refresh_token_expiry = token.refresh_token_expiry if token else False
            rec.datev_issued_by_name = token.issued_by_name if token else False
            rec.datev_granted_scopes = token.scope if token else False

    @api.model
    def _get_datev_config(self, company=None):
        company = (company or self.env.company).sudo()
        if (company.datev_mode or "off") == "off":
            raise UserError(
                _(
                    "DATEV ist für die Firma '%s' deaktiviert. Bitte in den "
                    "Einstellungen zuerst Sandbox oder Produktion wählen."
                )
                % company.name
            )
        # sudo: credentials are group-restricted (base.group_system), but the
        # API service must also work for e.g. accountants triggering an export
        # or HR users triggering a sync — without exposing the fields to them.
        return {
            "client_id": company.datev_client_id or "",
            "client_secret": company.datev_client_secret or "",
            "sandbox": company.datev_mode == "sandbox",
            "company_id": company.id,
        }

    def action_datev_connect(self):
        self.ensure_one()
        config = self._get_datev_config(self.company_id)
        if not config["client_id"] or not config["client_secret"]:
            raise UserError(_("Please enter your DATEV Client ID and Client Secret first."))
        self._datev_check_redirect_url(config["sandbox"])
        # Clear any previous error at the start of a fresh connection attempt.
        self.company_id.sudo().datev_last_error = False

        from ..services.datev_api import DatevApiService

        service = DatevApiService(self.env, config)
        if service.get_scope() == "openid profile":
            raise UserError(
                _(
                    "Bitte aktivieren Sie zuerst mindestens einen DATEV Datenservice "
                    "(z. B. DATEV Buchungsdatenservice) in den Einstellungen. "
                    "Es werden nur die Scopes angefragt, die Sie tatsächlich nutzen."
                )
            )
        auth_url = service.get_authorization_url()
        return {
            "type": "ir.actions.act_url",
            "url": auth_url,
            "target": "self",
        }

    def action_datev_disconnect(self):
        self.ensure_one()
        token = self.env["datev.token"].search([("company_id", "=", self.company_id.id)], limit=1)
        if token:
            token.action_disconnect()

    def action_datev_fetch_clients(self):
        """Open a scrollable selection dialog with all clients the token may
        access (name, consultant/client number, booked services)."""
        self.ensure_one()
        config = self._get_datev_config(self.company_id)

        from ..services.datev_api import DatevApiService
        from ..wizards.datev_client_select_wizard import _services_to_str

        service = DatevApiService(self.env, config)
        items = []
        top, skip = 100, 0
        # Paging per spec: top/skip, max. 100 per page.
        for _page in range(20):
            page_items = service.accounting_clients_list(top=top, skip=skip)
            items.extend(page_items)
            if len(page_items) < top:
                break
            skip += top
        if not items:
            raise UserError(_("No DATEV clients found. Please check your API product subscription."))

        wizard = self.env["datev.client.select.wizard"].create(
            {
                "company_id": self.company_id.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": c.get("name", ""),
                            "consultant_number": str(c.get("consultant_number", "")),
                            "client_number": str(c.get("client_number", "")),
                            "services": _services_to_str(c) or "–",
                        },
                    )
                    for c in items
                ],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("DATEV Mandant auswählen"),
            "res_model": "datev.client.select.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_datev_check_client(self):
        """Authorization check (MUST): confirm via GET /clients/{client-id}
        that the configured client exists, is accessible with this token and
        has the Buchungsdatenservice booked."""
        self.ensure_one()
        company = self.company_id
        client_id = company.datev_get_client_id()

        from ..services.datev_api import DatevApiService
        from ..wizards.datev_client_select_wizard import (
            _has_accounting_service,
            _services_to_str,
        )

        service = DatevApiService(self.env, self._get_datev_config(company))
        client = service.accounting_clients_get(client_id)
        services_str = _services_to_str(client) or "–"
        has_service = _has_accounting_service(services_str)
        company.write(
            {
                "datev_client_verified": has_service,
                "datev_client_check_info": ("%s — Services: %s" % (client.get("name", client_id), services_str))[:250],
            }
        )
        if not has_service:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("DATEV Mandantenprüfung"),
                    "message": _(
                        "Mandant %s ist erreichbar, aber der Buchungsdatenservice "
                        "ist nicht gebucht (Services: %s). Bitte beim Steuerberater/"
                        "DATEV aktivieren: http://go.datev.de/datenservices-einrichten"
                    )
                    % (client_id, services_str),
                    "type": "warning",
                    "sticky": True,
                },
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DATEV Mandantenprüfung"),
                "message": _("Mandant %s bestätigt — %s")
                % (
                    client.get("name", client_id),
                    services_str,
                ),
                "type": "success",
            },
        }
