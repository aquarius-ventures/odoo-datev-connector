import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# An authorization round-trip should not take longer than this; older flow
# records are treated as expired and rejected in the callback.
_FLOW_MAX_AGE_MINUTES = 10


class DatevOauthFlow(models.TransientModel):
    """One in-flight DATEV OAuth authorization (state/nonce/PKCE per attempt).

    Persisting each flow separately (instead of one global ir.config_parameter
    slot) makes parallel connects and multi-company setups safe: the callback
    resolves the company from the state parameter, and every record is
    single-use.
    """

    _name = "datev.oauth.flow"
    _description = "DATEV OAuth Flow (in-flight authorization)"
    _transient_max_hours = 1

    state = fields.Char(required=True, index=True)
    nonce = fields.Char(required=True)
    code_verifier = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, ondelete="cascade")
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")

    @api.model
    def _begin(self, state, nonce, code_verifier, company_id):
        self.sudo().create(
            {
                "state": state,
                "nonce": nonce,
                "code_verifier": code_verifier,
                "company_id": company_id,
                "user_id": self.env.uid,
            }
        )

    @api.model
    def _consume(self, state):
        """Return and delete the flow matching ``state`` (single-use).

        Returns a plain dict or None when the state is unknown or expired.
        """
        if not state:
            return None
        flow = self.sudo().search([("state", "=", state)], limit=1)
        if not flow:
            return None
        vals = {
            "nonce": flow.nonce,
            "code_verifier": flow.code_verifier,
            "company_id": flow.company_id.id,
            "user_id": flow.user_id.id,
            "create_date": flow.create_date,
        }
        flow.unlink()
        if vals["create_date"] < fields.Datetime.now() - timedelta(minutes=_FLOW_MAX_AGE_MINUTES):
            _logger.warning("DATEV OAuth: state expired (older than %s min).", _FLOW_MAX_AGE_MINUTES)
            return None
        return vals
