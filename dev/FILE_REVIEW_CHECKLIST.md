# DATEV Dateiprüfung (Pflichttermin „Technical review — file format“)

Vorbereitung der Musterdateien für die verpflichtende Prüfung des
DATEV-Formats. Grundlage: DATEV-Musterbelege und das offizielle
Prüfprogramm.

## Downloads

- Musterbelege: <https://developer.datev.de/assets/Musterbelege_1514b3d255.zip>
- DATEV-Format-Prüfprogramm (Windows):
  <https://developer.datev.de/assets/Datev_Format_Pruefprogramm_2_2_3_0_76439824cb.zip>

## Vorgehen

1. In einer Dev-Datenbank die Musterbelege je Use Case als Odoo-Belege
   erfassen (mind. **3 Datensätze je Sonderfall**):
   - Ausgangsrechnungen (mit 19 %/7 % USt, BU-Schlüssel gemappt)
   - Eingangsrechnungen (Vorsteuer)
   - Gutschrift / Rechnungskorrektur
   - Generalumkehr
2. Je Use Case über **DATEV → Accounting → Export to DATEV** mit
   `Export Mode = Download CSV` eine EXTF-Datei erzeugen.
   Wichtig: Zeitraum so wählen, dass er **ein** Wirtschaftsjahr trifft.
   Der Use Case muss in Header-Feld 17 (Bezeichnung) stehen — im Wizard
   bzw. Generator-Parameter `designation` setzen, z. B.
   `Ausgangsrechnungen 01/2026`.
3. Jede Datei mit dem Prüfprogramm validieren (Windows) und das Ergebnis
   hier abhaken. Erst wenn alle Dateien „grün“ sind, den Prüftermin buchen.

Hinweis odoo.sh: Dateien immer über die Web-UI erzeugen/herunterladen —
kein `odoo-bin` via SSH auf der Dev-Instanz starten.

## Checkliste

| Use Case | Datei | Prüfprogramm | Datum | Anmerkungen |
|---|---|---|---|---|
| Ausgangsrechnungen | | ☐ | | |
| Eingangsrechnungen | | ☐ | | |
| Gutschrift/Rechnungskorrektur | | ☐ | | |
| Generalumkehr | | ☐ | | |

## Erwartete Eckdaten der Dateien

- Header: `"EXTF";700;21;"Buchungsstapel";13;<17-stelliger Zeitstempel>;…`
  (31 Felder, Festschreibung standardmäßig `1`)
- Spaltenzeile: 125 Spalten, letzte Spalte `Abw. Skontokonto`
- Encoding CP1252, Zeilenende CRLF, Textfelder in `"…"`, Zahlen mit
  Dezimal-Komma
