"""
Parser for DATEV EXTF Buchungsstapel files (bidirectional import).

Used to import accounting data received from DATEV back into Odoo
(e.g. after a tax advisor has posted corrections).
"""

import csv
import io
import logging

_logger = logging.getLogger(__name__)


class ExtfParser:
    """Parses a DATEV EXTF CSV and returns structured data."""

    def parse(self, content: bytes) -> dict:
        text = content.decode("utf-8-sig")  # strip BOM
        reader = csv.reader(io.StringIO(text), delimiter=";")
        rows = list(reader)
        if not rows or not rows[0][0].startswith("EXTF"):
            raise ValueError("Not a valid DATEV EXTF file.")
        header = rows[0]
        column_row = rows[1]
        data_rows = rows[2:]
        return {
            "header": header,
            "columns": column_row,
            "entries": [dict(zip(column_row, row)) for row in data_rows if any(row)],
        }
