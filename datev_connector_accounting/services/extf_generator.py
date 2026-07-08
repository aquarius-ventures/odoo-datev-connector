"""
DATEV EXTF Buchungsstapel generator.

Specification: DATEV-Format v700, Buchungsstapel format version 13
(developer.datev.de → File formats → DATEV-Format). The column header row and
the 31-field file header follow the official portal sample 1:1.

Encoding: CP1252. That is the DATEV Accounting default; Unicode would require
a BOM and is not supported by the DATEV-Format Prüfprogramm, so CP1252 is the
robust choice for the mandatory file review ("Technical review - file format").

Posting logic (P0.5 decision — must be explained at the DATEV release meeting):
Every move is exported pivot-style. The pivot line is the receivable/payable
line (largest one if several), otherwise the line with the largest amount.
Only the non-pivot lines are exported; the pivot account is their Gegenkonto.

Tax handling:
- Variant B (DATEV default): if every tax posted on the move has a
  BU-Schlüssel mapping (datev.tax.mapping), base lines are exported GROSS
  with the BU key in column 9 and the Odoo tax lines are skipped — DATEV
  recomputes the tax on the automatic account.
- Variant A (fallback): without complete BU mappings, base lines are exported
  net and the tax lines are exported as separate rows. The DATEV accounts
  mapped for the tax accounts must then be non-automatic accounts.

Foreign currency: moves not in the company currency are rejected with a
UserError (fields 3-6 Kurs/Basis-Umsatz are intentionally not half-filled).
"""

import logging
import re
from datetime import date, datetime, timedelta
from typing import Dict, List

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_EXTF_VERSION = 700
_FORMAT_TYPE = 21  # Buchungsstapel
_FORMAT_NAME = "Buchungsstapel"
_FORMAT_VERSION = 13
_CREATED_BY_APP = "Odoo DATEV Connector"

# Allowed characters in Belegfeld 1/2 per spec: \w plus $ & % * + - /
_BELEGFELD_ALLOWED = re.compile(r"[^A-Za-z0-9_$&%*+\-/]")
# Control characters are forbidden inside text fields.
_CONTROL_CHARS = re.compile(r"[\r\n\t\x00-\x1f]")


class ExtfGenerator:
    """Generates a DATEV EXTF Buchungsstapel CSV (v700/13) in memory."""

    # Column header row of format version 13 (125 columns), taken verbatim from
    # the official sample in the DATEV-Format guide ("Getting started").
    _COLUMNS = (
        "Umsatz (ohne Soll/Haben-Kz);Soll/Haben-Kennzeichen;WKZ Umsatz;Kurs;"
        "Basis-Umsatz;WKZ Basis-Umsatz;Konto;Gegenkonto (ohne BU-Schlüssel);"
        "BU-Schlüssel;Belegdatum;Belegfeld 1;Belegfeld 2;Skonto;Buchungstext;"
        "Postensperre;Diverse Adressnummer;Geschäftspartnerbank;Sachverhalt;"
        "Zinssperre;Beleglink;"
        "Beleginfo - Art 1;Beleginfo - Inhalt 1;Beleginfo - Art 2;Beleginfo - Inhalt 2;"
        "Beleginfo - Art 3;Beleginfo - Inhalt 3;Beleginfo - Art 4;Beleginfo - Inhalt 4;"
        "Beleginfo - Art 5;Beleginfo - Inhalt 5;Beleginfo - Art 6;Beleginfo - Inhalt 6;"
        "Beleginfo - Art 7;Beleginfo - Inhalt 7;Beleginfo - Art 8;Beleginfo - Inhalt 8;"
        "KOST1 - Kostenstelle;KOST2 - Kostenstelle;Kost-Menge;"
        "EU-Land u. UStID (Bestimmung);EU-Steuersatz (Bestimmung);"
        "Abw. Versteuerungsart;Sachverhalt L+L;Funktionsergänzung L+L;"
        "BU 49 Hauptfunktionstyp;BU 49 Hauptfunktionsnummer;BU 49 Funktionsergänzung;"
        "Zusatzinformation - Art 1;Zusatzinformation- Inhalt 1;"
        "Zusatzinformation - Art 2;Zusatzinformation- Inhalt 2;"
        "Zusatzinformation - Art 3;Zusatzinformation- Inhalt 3;"
        "Zusatzinformation - Art 4;Zusatzinformation- Inhalt 4;"
        "Zusatzinformation - Art 5;Zusatzinformation- Inhalt 5;"
        "Zusatzinformation - Art 6;Zusatzinformation- Inhalt 6;"
        "Zusatzinformation - Art 7;Zusatzinformation- Inhalt 7;"
        "Zusatzinformation - Art 8;Zusatzinformation- Inhalt 8;"
        "Zusatzinformation - Art 9;Zusatzinformation- Inhalt 9;"
        "Zusatzinformation - Art 10;Zusatzinformation- Inhalt 10;"
        "Zusatzinformation - Art 11;Zusatzinformation- Inhalt 11;"
        "Zusatzinformation - Art 12;Zusatzinformation- Inhalt 12;"
        "Zusatzinformation - Art 13;Zusatzinformation- Inhalt 13;"
        "Zusatzinformation - Art 14;Zusatzinformation- Inhalt 14;"
        "Zusatzinformation - Art 15;Zusatzinformation- Inhalt 15;"
        "Zusatzinformation - Art 16;Zusatzinformation- Inhalt 16;"
        "Zusatzinformation - Art 17;Zusatzinformation- Inhalt 17;"
        "Zusatzinformation - Art 18;Zusatzinformation- Inhalt 18;"
        "Zusatzinformation - Art 19;Zusatzinformation- Inhalt 19;"
        "Zusatzinformation - Art 20;Zusatzinformation- Inhalt 20;"
        "Stück;Gewicht;Zahlweise;Forderungsart;Veranlagungsjahr;"
        "Zugeordnete Fälligkeit;Skontotyp;Auftragsnummer;Buchungstyp;"
        "USt-Schlüssel (Anzahlungen);EU-Land (Anzahlungen);"
        "Sachverhalt L+L (Anzahlungen);EU-Steuersatz (Anzahlungen);"
        "Erlöskonto (Anzahlungen);Herkunft-Kz;Buchungs GUID;KOST-Datum;"
        "SEPA-Mandatsreferenz;Skontosperre;Gesellschaftername;Beteiligtennummer;"
        "Identifikationsnummer;Zeichnernummer;Postensperre bis;"
        "Bezeichnung SoBil-Sachverhalt;Kennzeichen SoBil-Buchung;Festschreibung;"
        "Leistungsdatum;Datum Zuord. Steuerperiode;Fälligkeit;Generalumkehr (GU);"
        "Steuersatz;Land;Abrechnungsreferenz;BVV-Position;"
        "EU-Land u. UStID (Ursprung);EU-Steuersatz (Ursprung);Abw. Skontokonto"
    ).split(";")

    # 1-based indices of text columns. Text columns are always written quoted
    # (empty text = ""), all other columns are numeric and never quoted
    # (empty numeric = empty field). Derived from the field expressions in the
    # "Booking batch" format description.
    _TEXT_COLUMNS = frozenset(
        [2, 3, 6, 9, 11, 12, 14, 16, 20]
        + list(range(21, 39))            # Beleginfo 1-8, KOST1, KOST2
        + [40, 42]
        + list(range(48, 88))            # Zusatzinformation 1-20
        + [91, 95, 96, 98, 102, 103, 105, 107, 109, 110, 112, 118, 120, 121, 123]
    )

    def __init__(self, env, company, date_from: date, date_to: date, designation: str = ""):
        self._env = env
        self._company = company
        self._date_from = date_from
        self._date_to = date_to
        self._designation = designation
        self._mapping_cache: Dict[int, str] = {}
        self._bu_key_cache: Dict[int, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, moves) -> bytes:
        if not moves:
            raise UserError("No journal entries to export.")
        self._validate_fiscal_year()
        self._build_mapping_caches()
        lines = [self._render_header(), ";".join(self._COLUMNS)]
        for move in moves:
            self._validate_move_currency(move)
            for row in self._move_rows(move):
                lines.append(self._render_row(row))
        content = "\r\n".join(lines) + "\r\n"
        # CP1252 is the DATEV Accounting default charset; characters outside
        # CP1252 are replaced rather than crashing the export.
        return content.encode("cp1252", errors="replace")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _fiscal_year_start(self) -> date:
        fiscal_last_month = int(self._company.fiscalyear_last_month or 12)
        fiscal_last_day = int(self._company.fiscalyear_last_day or 31)
        fy_end_in_year = date(self._date_from.year, fiscal_last_month, fiscal_last_day)
        if self._date_from <= fy_end_in_year:
            return date(self._date_from.year - 1, fiscal_last_month, fiscal_last_day) + timedelta(days=1)
        return fy_end_in_year + timedelta(days=1)

    def _validate_fiscal_year(self):
        """The Belegdatum has no year (DDMM), so a batch must not span fiscal years."""
        if self._date_from > self._date_to:
            raise UserError("DATEV export: 'From' date must not be after 'To' date.")
        fy_start = self._fiscal_year_start()
        fy_end = date(fy_start.year + 1, fy_start.month, fy_start.day) - timedelta(days=1)
        if self._date_to > fy_end:
            raise UserError(
                "DATEV export: the period %s – %s spans more than one fiscal year "
                "(fiscal year: %s – %s). Please export each fiscal year separately."
                % (self._date_from, self._date_to, fy_start, fy_end)
            )

    def _validate_move_currency(self, move):
        company_currency = self._company.currency_id
        if move.currency_id and move.currency_id != company_currency:
            raise UserError(
                "DATEV export: journal entry %s is in %s. Foreign-currency export "
                "(Kurs/Basis-Umsatz) is not supported — please exclude this entry."
                % (move.name, move.currency_id.name)
            )

    # ------------------------------------------------------------------
    # Mapping caches
    # ------------------------------------------------------------------

    def _build_mapping_caches(self):
        mappings = self._env["datev.account.mapping"].search(
            [("company_id", "=", self._company.id)]
        )
        self._mapping_cache = {m.account_id.id: m.datev_account_number for m in mappings}
        tax_mappings = self._env["datev.tax.mapping"].search(
            [("company_id", "=", self._company.id)]
        )
        self._bu_key_cache = {m.tax_id.id: m.datev_bu_key for m in tax_mappings}

    def _resolve_account(self, account) -> str:
        number = self._mapping_cache.get(account.id)
        if not number:
            # Fall back to the Odoo account code stripped of non-digits
            number = "".join(filter(str.isdigit, account.code)) or account.code
            _logger.debug(
                "No DATEV mapping for account %s – using code %s", account.code, number
            )
        return number

    # ------------------------------------------------------------------
    # Header (31 fields, v700)
    # ------------------------------------------------------------------

    def _render_header(self) -> str:
        consultant_number = self._company.datev_consultant_number or ""
        client_number = self._company.datev_client_number or ""
        fy_start = self._fiscal_year_start()
        now = datetime.now()
        created_at = now.strftime("%Y%m%d%H%M%S") + "%03d" % (now.microsecond // 1000)
        designation = self._designation or "Odoo %s-%s" % (
            self._date_from.strftime("%d.%m."), self._date_to.strftime("%d.%m.%Y"),
        )
        # Bezeichnung: max 30 chars, allowed [\w.-/ ]
        designation = re.sub(r"[^\w.\-/ ]", " ", designation)[:30]
        festschreibung = "1" if self._company.datev_extf_festschreibung else "0"
        chart = self._company.datev_chart_of_accounts or ""

        def q(s):
            return '"%s"' % s

        fields = [
            q("EXTF"),                                    # 1  Kennzeichen
            str(_EXTF_VERSION),                           # 2  Versionsnummer
            str(_FORMAT_TYPE),                            # 3  Formatkategorie
            q(_FORMAT_NAME),                              # 4  Formatname
            str(_FORMAT_VERSION),                         # 5  Formatversion
            created_at,                                   # 6  Erzeugt am (YYYYMMDDHHMMSSFFF)
            "",                                           # 7  Importiert (set by DATEV)
            q("OO"),                                      # 8  Herkunft (2-char origin mark)
            q(_CREATED_BY_APP[:25]),                      # 9  Exportiert von
            q(""),                                        # 10 Importiert von
            consultant_number,                            # 11 Beraternummer
            client_number,                                # 12 Mandantennummer
            fy_start.strftime("%Y%m%d"),                  # 13 WJ-Beginn
            self._company.datev_account_number_length or "4",  # 14 Sachkontenlänge
            self._date_from.strftime("%Y%m%d"),           # 15 Datum von
            self._date_to.strftime("%Y%m%d"),             # 16 Datum bis
            q(designation),                               # 17 Bezeichnung
            q(""),                                        # 18 Diktatkürzel
            "1",                                          # 19 Buchungstyp (1 = Fibu)
            "0",                                          # 20 Rechnungslegungszweck
            festschreibung,                               # 21 Festschreibung
            q("EUR"),                                     # 22 WKZ
            "",                                           # 23 Reserviert
            q(""),                                        # 24 Derivatskennzeichen
            "",                                           # 25 Reserviert
            "",                                           # 26 Reserviert
            q(chart),                                     # 27 Sachkontenrahmen
            "",                                           # 28 ID der Branchenlösung
            "",                                           # 29 Reserviert
            q(""),                                        # 30 Reserviert
            q(""),                                        # 31 Anwendungsinformation
        ]
        return ";".join(fields)

    # ------------------------------------------------------------------
    # Data rows
    # ------------------------------------------------------------------

    @staticmethod
    def _format_amount(amount: float) -> str:
        return ("%.2f" % abs(amount)).replace(".", ",")

    @staticmethod
    def _sanitize_text(text: str, max_len: int) -> str:
        return _CONTROL_CHARS.sub(" ", text or "").strip()[:max_len]

    @staticmethod
    def _sanitize_belegfeld(text: str, max_len: int = 36) -> str:
        return _BELEGFELD_ALLOWED.sub("", text or "")[:max_len]

    def _render_row(self, row: List[str]) -> str:
        """Apply per-column typing: text columns quoted (quotes doubled),
        numeric columns unquoted, empty fields typed accordingly."""
        rendered = []
        for idx, value in enumerate(row, start=1):
            value = value or ""
            if idx in self._TEXT_COLUMNS:
                rendered.append('"%s"' % value.replace('"', '""'))
            else:
                rendered.append(value)
        return ";".join(rendered)

    def _move_rows(self, move) -> List[List[str]]:
        currency = self._company.currency_id
        lines = [
            line for line in move.line_ids
            if line.account_id
            and line.display_type not in ("line_section", "line_note")
            and not currency.is_zero(line.balance)
        ]
        if not lines:
            return []

        pivot = self._pick_pivot(lines)
        tax_lines = [line for line in lines if line.tax_line_id and line != pivot]
        base_lines = [line for line in lines if line != pivot and not line.tax_line_id]

        # Variant B requires a BU key for every posted tax and at most one tax
        # per base line; otherwise fall back to variant A (see module docstring).
        gross_mode = bool(tax_lines) and all(
            t.tax_line_id.id in self._bu_key_cache for t in tax_lines
        ) and all(len(line.tax_ids) <= 1 for line in base_lines)

        extra = None
        if gross_mode:
            extra = self._allocate_tax_to_base_lines(base_lines, tax_lines)

        rows = []
        if extra is not None:
            for line in base_lines:
                signed = line.balance + extra.get(line.id, 0.0)
                bu_key = ""
                if line.tax_ids:
                    bu_key = self._bu_key_cache.get(line.tax_ids[0].id, "")
                rows.append(self._line_row(move, line, pivot, signed, bu_key))
        else:
            if tax_lines:
                _logger.info(
                    "DATEV export: move %s exported with separate tax rows "
                    "(variant A) — incomplete BU-Schlüssel mapping or "
                    "unallocatable tax.", move.name,
                )
            for line in base_lines + tax_lines:
                rows.append(self._line_row(move, line, pivot, line.balance, ""))
        return rows

    @staticmethod
    def _pick_pivot(lines):
        """Pivot = receivable/payable line (largest when several), otherwise
        the line with the largest absolute amount."""
        rp_lines = [
            line for line in lines
            if line.account_id.account_type in ("asset_receivable", "liability_payable")
        ]
        pool = rp_lines or lines
        return max(pool, key=lambda line: abs(line.balance))

    def _allocate_tax_to_base_lines(self, base_lines, tax_lines):
        """Distribute the booked tax amounts onto their base lines so the sum of
        the exported gross rows equals base + tax exactly (residual goes to the
        largest base line per tax). Returns None when a tax amount cannot be
        allocated — the caller then falls back to variant A to stay balanced."""
        extra: Dict[int, float] = {}
        totals: Dict[int, float] = {}
        for tline in tax_lines:
            totals[tline.tax_line_id.id] = totals.get(tline.tax_line_id.id, 0.0) + tline.balance
        for tax_id, total_tax in totals.items():
            blines = [line for line in base_lines if tax_id in line.tax_ids.ids]
            if not blines:
                # No base line references the tax (e.g. manual tax adjustment).
                _logger.info(
                    "DATEV export: tax line without matching base line "
                    "(tax id %s, amount %.2f) — falling back to variant A.",
                    tax_id, total_tax,
                )
                return None
            total_base = sum(line.balance for line in blines)
            remaining = total_tax
            blines_sorted = sorted(blines, key=lambda line: abs(line.balance))
            for line in blines_sorted[:-1]:
                share = round(total_tax * (line.balance / total_base), 2) if total_base else 0.0
                extra[line.id] = extra.get(line.id, 0.0) + share
                remaining -= share
            last = blines_sorted[-1]
            extra[last.id] = extra.get(last.id, 0.0) + round(remaining, 2)
        return extra

    def _line_row(self, move, line, pivot, signed_amount: float, bu_key: str) -> List[str]:
        row = [""] * len(self._COLUMNS)
        row[0] = self._format_amount(signed_amount)             # 1 Umsatz
        row[1] = "S" if signed_amount > 0 else "H"              # 2 Soll/Haben
        row[2] = self._company.currency_id.name or "EUR"        # 3 WKZ Umsatz
        row[6] = self._resolve_account(line.account_id)         # 7 Konto
        row[7] = self._resolve_account(pivot.account_id)        # 8 Gegenkonto
        row[8] = bu_key                                         # 9 BU-Schlüssel
        row[9] = move.date.strftime("%d%m") if move.date else ""  # 10 Belegdatum (DDMM)
        row[10] = self._sanitize_belegfeld(move.ref or move.name or "")  # 11 Belegfeld 1
        row[13] = self._sanitize_text(line.name or move.name or "", 60)  # 14 Buchungstext
        return row
