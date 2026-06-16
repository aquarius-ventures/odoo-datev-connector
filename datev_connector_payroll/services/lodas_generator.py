"""
DATEV LODAS ASCII export generator.

Generates a LODAS-compatible ASCII file for payroll data transfer.
Format specification: DATEV LODAS Schnittstellenbeschreibung (available via
developer.datev.de after accepting the developer agreement).

NOTE: The exact field layout depends on the DATEV LODAS version and the
specific API endpoint agreed upon in the developer portal.  This module
provides the structural skeleton and must be validated against the actual
DATEV LODAS specification once the developer agreement is active.
"""

import io
import logging
from datetime import date

_logger = logging.getLogger(__name__)

_LODAS_HEADER_VERSION = "1.0"
_LODAS_SOURCE_SYSTEM = "Odoo"


class LodasGenerator:
    """Generates a DATEV LODAS ASCII payroll file."""

    def __init__(self, env, company):
        self._env = env
        self._company = company

    def generate(self, payslips) -> bytes:
        output = io.StringIO()
        self._write_header(output)
        for slip in payslips:
            self._write_payslip(output, slip)
        self._write_footer(output)
        return output.getvalue().encode("cp1252")  # LODAS uses Windows-1252

    def _write_header(self, output: io.StringIO):
        consultant_number = (
            self._env["ir.config_parameter"]
            .sudo()
            .get_param("datev_connector.consultant_number", "")
        )
        client_number = (
            self._env["ir.config_parameter"]
            .sudo()
            .get_param("datev_connector.client_number", "")
        )
        output.write(f"[Allgemein]\n")
        output.write(f"Erstelldatum={date.today().strftime('%d.%m.%Y')}\n")
        output.write(f"Beraternummer={consultant_number}\n")
        output.write(f"Mandantennummer={client_number}\n")
        output.write(f"Quellsystem={_LODAS_SOURCE_SYSTEM}\n\n")
        output.write("[Arbeitnehmer]\n")

    def _write_payslip(self, output: io.StringIO, slip):
        mapping = self._env["datev.employee.mapping"].search(
            [("employee_id", "=", slip.employee_id.id)], limit=1
        )
        personnel_number = mapping.datev_personnel_number if mapping else ""
        if not personnel_number:
            _logger.warning(
                "Employee %s has no DATEV personnel number – skipping payslip %s",
                slip.employee_id.name,
                slip.name,
            )
            return
        output.write(f"Personalnummer={personnel_number}\n")
        output.write(f"Name={slip.employee_id.name}\n")
        for line in slip.line_ids:
            if line.amount == 0:
                continue
            output.write(f"{line.code}={line.amount:.2f}\n")
        output.write("\n")

    def _write_footer(self, output: io.StringIO):
        output.write("[Ende]\n")
