"""
DATEV EXTF Buchungsstapel generator.

Specification: https://developer.datev.de/en/product-detail/accounting-extf-files/2.0
Format version: EXTF 700, record type 21 (Buchungsstapel).
"""

import csv
import io
import logging
from datetime import date, timedelta
from typing import Dict

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# EXTF header field positions are fixed by DATEV spec
_EXTF_VERSION = 700
_FORMAT_TYPE = 21  # Buchungsstapel
_FORMAT_NAME = "Buchungsstapel"
_FORMAT_VERSION = 7
_CREATED_BY_APP = "Odoo DATEV Connector"
_CONSULTANT_NUMBER_PLACEHOLDER = ""  # filled from company config
_CLIENT_NUMBER_PLACEHOLDER = ""


class ExtfGenerator:
    """Generates a DATEV EXTF Buchungsstapel CSV in memory."""

    # Column order as per DATEV spec (Buchungsstapel v7)
    _COLUMNS = [
        "Umsatz (ohne Soll/Haben-Kz)",  # 1
        "Soll/Haben-Kennzeichen",  # 2
        "WKZ Umsatz",  # 3
        "Kurs",  # 4
        "Basis-Umsatz",  # 5
        "WKZ Basis-Umsatz",  # 6
        "Konto",  # 7
        "Gegenkonto (ohne BU-Schlüssel)",  # 8
        "BU-Schlüssel",  # 9
        "Belegdatum",  # 10
        "Belegfeld 1",  # 11
        "Belegfeld 2",  # 12
        "Skonto",  # 13
        "Buchungstext",  # 14
        "Postensperre",  # 15
        "Diverse Adressnummer",  # 16
        "Geschäftspartnerbank",  # 17
        "Sachverhalt",  # 18
        "Zinssperre",  # 19
        "Beleglink",  # 20
        "Beleginfo - Art 1",  # 21
        "Beleginfo - Inhalt 1",  # 22
        "Beleginfo - Art 2",  # 23
        "Beleginfo - Inhalt 2",  # 24
        "Beleginfo - Art 3",  # 25
        "Beleginfo - Inhalt 3",  # 26
        "Beleginfo - Art 4",  # 27
        "Beleginfo - Inhalt 4",  # 28
        "Beleginfo - Art 5",  # 29
        "Beleginfo - Inhalt 5",  # 30
        "Beleginfo - Art 6",  # 31
        "Beleginfo - Inhalt 6",  # 32
        "Beleginfo - Art 7",  # 33
        "Beleginfo - Inhalt 7",  # 34
        "Beleginfo - Art 8",  # 35
        "Beleginfo - Inhalt 8",  # 36
        "KOST1 - Kostenstelle",  # 37
        "KOST2 - Kostenstelle",  # 38
        "KOST-Menge",  # 39
        "EU-Land u. UStID",  # 40
        "EU-Steuersatz",  # 41
        "Abw. Versteuerungsart",  # 42
        "Sachverhalt L+L",  # 43
        "Funktionsergänzung L+L",  # 44
        "BU 49 Hauptfunktionstyp",  # 45
        "BU 49 Hauptfunktionsnummer",  # 46
        "BU 49 Funktionsergänzung",  # 47
        "Zusatzinformation - Art 1",  # 48
        "Zusatzinformation - Inhalt 1",  # 49
        "Zusatzinformation - Art 2",  # 50
        "Zusatzinformation - Inhalt 2",  # 51
        "Zusatzinformation - Art 3",  # 52
        "Zusatzinformation - Inhalt 3",  # 53
        "Zusatzinformation - Art 4",  # 54
        "Zusatzinformation - Inhalt 4",  # 55
        "Zusatzinformation - Art 5",  # 56
        "Zusatzinformation - Inhalt 5",  # 57
        "Zusatzinformation - Art 6",  # 58
        "Zusatzinformation - Inhalt 6",  # 59
        "Zusatzinformation - Art 7",  # 60
        "Zusatzinformation - Inhalt 7",  # 61
        "Zusatzinformation - Art 8",  # 62
        "Zusatzinformation - Inhalt 8",  # 63
        "Zusatzinformation - Art 9",  # 64
        "Zusatzinformation - Inhalt 9",  # 65
        "Zusatzinformation - Art 10",  # 66
        "Zusatzinformation - Inhalt 10",  # 67
        "Zusatzinformation - Art 11",  # 68
        "Zusatzinformation - Inhalt 11",  # 69
        "Zusatzinformation - Art 12",  # 70
        "Zusatzinformation - Inhalt 12",  # 71
        "Zusatzinformation - Art 13",  # 72
        "Zusatzinformation - Inhalt 13",  # 73
        "Zusatzinformation - Art 14",  # 74
        "Zusatzinformation - Inhalt 14",  # 75
        "Zusatzinformation - Art 15",  # 76
        "Zusatzinformation - Inhalt 15",  # 77
        "Zusatzinformation - Art 16",  # 78
        "Zusatzinformation - Inhalt 16",  # 79
        "Zusatzinformation - Art 17",  # 80
        "Zusatzinformation - Inhalt 17",  # 81
        "Zusatzinformation - Art 18",  # 82
        "Zusatzinformation - Inhalt 18",  # 83
        "Zusatzinformation - Art 19",  # 84
        "Zusatzinformation - Inhalt 19",  # 85
        "Zusatzinformation - Art 20",  # 86
        "Zusatzinformation - Inhalt 20",  # 87
        "Stück",  # 88
        "Gewicht",  # 89
        "Zahlweise",  # 90
        "Forderungsart",  # 91
        "Veranlagungsjahr",  # 92
        "Zugeordnete Fälligkeit",  # 93
        "Skontotyp",  # 94
        "Auftragsnummer",  # 95
        "Buchungstyp",  # 96
        "USt-Schlüssel (Anzahlungen)",  # 97
        "EU-Land (Anzahlungen)",  # 98
        "Sachverhalt L+L (Anzahlungen)",  # 99
        "EU-Steuersatz (Anzahlungen)",  # 100
        "Erlöskonto (Anzahlungen)",  # 101
        "Herkunft-Kz",  # 102
        "Buchungs GUID",  # 103
        "KOST-Datum",  # 104
        "SEPA-Mandatsreferenz",  # 105
        "Skontosperre",  # 106
        "Gesellschaftername",  # 107
        "Beteiligtennummer",  # 108
        "Identifikationsnummer",  # 109
        "Zeichnernummer",  # 110
        "Postensperre bis",  # 111
        "Bezeichnung SoBil-Sachverhalt",  # 112
        "Kennzeichen SoBil-Buchung",  # 113
        "Festschreibung",  # 114
        "Leistungsdatum",  # 115
        "Datum Zuord. Steuerperiode",  # 116
        "Fälligkeit",  # 117
        "Generalumkehr (GU)",  # 118
        "Steuersatz",  # 119
        "Land",  # 120
        "Abrechnungsreferenz",  # 121
        "BVV-Position (Betriebsvermögensvergleich)",  # 122
        "EU-Mitgliedstaat u. UStID (Ursprung)",  # 123
        "EU-Steuersatz (Ursprung)",  # 124
    ]

    def __init__(self, env, company, date_from: date, date_to: date):
        self._env = env
        self._company = company
        self._date_from = date_from
        self._date_to = date_to
        self._mapping_cache: Dict[int, str] = {}

    def generate(self, moves) -> bytes:
        if not moves:
            raise UserError("No journal entries to export.")
        self._build_mapping_cache()
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        self._write_header(writer)
        writer.writerow(self._COLUMNS)
        for move in moves:
            self._write_move(writer, move)
        content = output.getvalue()
        return ("﻿" + content).encode("utf-8")  # BOM required by DATEV

    def _build_mapping_cache(self):
        mappings = self._env["datev.account.mapping"].search(
            [("company_id", "=", self._company.id)]
        )
        self._mapping_cache = {m.account_id.id: m.datev_account_number for m in mappings}

    def _resolve_account(self, account) -> str:
        number = self._mapping_cache.get(account.id)
        if not number:
            # Fall back to the Odoo account code stripped of non-digits
            number = "".join(filter(str.isdigit, account.code)) or account.code
            _logger.debug(
                "No DATEV mapping for account %s – using code %s", account.code, number
            )
        return number

    def _write_header(self, writer):
        now = self._env.cr.now() if hasattr(self._env.cr, "now") else date.today()
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
        fiscal_last_month = int(self._company.fiscalyear_last_month or 12)
        fiscal_last_day = int(self._company.fiscalyear_last_day or 31)
        fy_end_in_year = date(self._date_from.year, fiscal_last_month, fiscal_last_day)
        if self._date_from <= fy_end_in_year:
            fy_start = date(self._date_from.year - 1, fiscal_last_month, fiscal_last_day) + timedelta(days=1)
        else:
            fy_start = fy_end_in_year + timedelta(days=1)
        writer.writerow(
            [
                "EXTF",
                _EXTF_VERSION,
                _FORMAT_TYPE,
                _FORMAT_NAME,
                _FORMAT_VERSION,
                "",  # reserved
                "",  # reserved
                "",  # reserved
                "",  # reserved
                "",  # reserved
                consultant_number,
                client_number,
                "",  # Sachkontonummernlänge (auto)
                fy_start.strftime("%Y%m%d"),
                self._date_from.strftime("%Y%m%d"),
                self._date_to.strftime("%Y%m%d"),
                "",  # Bezeichnung
                "",  # Diktatkürzel
                1,   # Buchungstyp: 1 = Fibu, 2 = Jahresabschluss
                0,   # Rechnungslegungszweck
                0,   # Festschreibung: 0 = keine
                self._company.currency_id.name or "EUR",
                "",  # reserved
                "",  # Derivatskennzeichen
                "",  # reserved
                "",  # reserved
                "",  # SKR
                "",  # Branchenlösung-ID
                "",  # reserved
                "",  # reserved
                _CREATED_BY_APP,
                "",  # Exportiert von
                now.strftime("%Y%m%d%H%M%S") if hasattr(now, "strftime") else "",
                "",  # Interne Bezeichnung
            ]
        )

    def _write_move(self, writer, move):
        for line in move.line_ids:
            if not line.account_id or line.display_type in ("line_section", "line_note"):
                continue
            amount = abs(line.balance)
            if amount == 0:
                continue
            debit_credit = "S" if line.balance > 0 else "H"
            konto = self._resolve_account(line.account_id)
            # For each line we need a counter-account; use the first other line
            # that is on a different account.  For simple moves this is correct;
            # for complex moves the accountant may need to review.
            gegenkonto = self._get_gegenkonto(move, line)
            row = [""] * len(self._COLUMNS)
            row[0] = f"{amount:.2f}".replace(".", ",")  # German decimal
            row[1] = debit_credit
            row[2] = move.currency_id.name or "EUR"
            row[6] = konto
            row[7] = gegenkonto
            row[9] = move.date.strftime("%d%m") if move.date else ""
            row[10] = (move.ref or move.name or "")[:12]
            text = (line.name or move.name or "").replace("\n", " ").replace("\r", "")
            row[13] = text[:60]
            writer.writerow(row)

    def _get_gegenkonto(self, move, current_line) -> str:
        candidates = [
            l for l in move.line_ids
            if l.id != current_line.id
            and l.display_type not in ("line_section", "line_note")
            and l.account_id
            and l.balance != 0
        ]
        if not candidates:
            return ""
        # Prefer a line with opposite sign — picks AR/AP as gegenkonto for expense/revenue lines
        opposite = [l for l in candidates if (l.balance > 0) != (current_line.balance > 0)]
        pool = opposite if opposite else candidates
        return self._resolve_account(max(pool, key=lambda l: abs(l.balance)).account_id)
