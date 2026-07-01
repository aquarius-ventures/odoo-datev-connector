"""Move legacy global DATEV settings (ir.config_parameter) onto the main company.

Before 17.0.1.0.8 the DATEV connection settings were stored as global
ir.config_parameter. They now live per company on res.company. Copy the existing
global values onto the main company so an existing single-Mandant setup keeps
working after the upgrade.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_STR_PARAMS = {
    "datev_connector.client_id": "datev_client_id",
    "datev_connector.client_secret": "datev_client_secret",
    "datev_connector.consultant_number": "datev_consultant_number",
    "datev_connector.client_number": "datev_client_number",
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    ICP = env["ir.config_parameter"].sudo()
    company = env.ref("base.main_company", raise_if_not_found=False) or \
        env["res.company"].search([], limit=1)
    if not company:
        return

    vals = {}
    for param, field in _STR_PARAMS.items():
        val = ICP.get_param(param)
        if val and not company[field]:
            vals[field] = val

    length = ICP.get_param("datev_connector.account_number_length")
    if length and (company.datev_account_number_length or "4") == "4":
        vals["datev_account_number_length"] = length

    sandbox = ICP.get_param("datev_connector.sandbox_mode")
    if sandbox and not company.datev_sandbox_mode:
        vals["datev_sandbox_mode"] = sandbox == "True"

    if vals:
        company.write(vals)
        _logger.info("DATEV: migrated global settings onto company %s: %s",
                     company.name, list(vals))
