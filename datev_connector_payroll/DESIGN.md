# DATEV Payroll Connector — Design (Entwurf)

Status: **Entwurf zur Abstimmung** — noch kein funktionaler Code.
Ziel: Bewertung + Blaupause, ob/wie das Lohn-Modul die komplexen Vergütungs-
bestandteile abbilden und an DATEV (`hr:exchange`, Payroll) übertragen kann.

---

## 1. Ziel & Scope

**In Scope**
- Import von Abrechnungszeilen (zunächst **JSON-Datei**; später dieselbe Logik
  hinter einer REST-API — *REST out of scope*).
- **Lohnarten-Katalog & Mapping** (Administration in Odoo).
- Abrechnungszeilen **einsehbar, vorschaubar, änderbar/ergänzbar** vor dem Transfer.
- Übertragung an DATEV via `month-records` (Primärkanal), optional
  `gross-payments` / `hourly-wages`.
- **LODAS und LuG**, umschaltbar pro Company (Pflicht-Konfiguration).

**Out of Scope (vorerst)**
- REST-Endpoint für den Import (nur das JSON-Format wird vorbereitet).
- Eigene Lohnberechnung in Odoo (Odoo ist zunächst Durchleitung + Review).
- Anlage von Lohnarten in DATEV (die API referenziert nur Nummern).

---

## 2. DATEV-API — verfügbare Kanäle

| Kanal | Endpoint | Schema-Felder | Zweck |
|---|---|---|---|
| **month-records** | `POST /clients/{client-id}/month-records` | `personnel_number`, `salary_type_id` (1–9999), `value` (−999.999,99…999.999,99), `differing_factor` (0…99,99), `cost_center_id` (≤13) | Bewegungsdaten pro Zeitraum — **beliebig viele Zeilen/Mitarbeiter** |
| **gross-payments** | `.../employees/{nr}/gross-payments` | `id`, `salary_type_id`, `amount`, `payment_months` (z. B. `1,…,12`) | Feste/wiederkehrende Bezüge |
| **hourly-wages** | `.../employees/{nr}/hourly-wages` | `id` (1–5), `amount` (0–99,99) | Stundenlohn-Sätze (max. 5 Slots) |

Alle async (202 + Job) — Status-Polling analog zum HR-Modul (`.../jobs/{uuid}`).
`Target-System`-Header: `lodas` oder `lug`. `reference-date` (yyyy-MM) je Request.

**Wichtig:** Das Portal exportiert **alles als Bewegungszeilen** (auch Gehalt,
Lohnart 10). Daher ist `month-records` der Primärkanal für den Import;
`gross-payments`/`hourly-wages` bleiben für einen späteren Stammdaten-Pfad optional.

---

## 3. Lohnarten-Katalog (eure Codes)

| Kategorie | Codes |
|---|---|
| fest / regelmäßig | 10 Gehalt, 20 Aushilfsgehalt |
| fest / unregelmäßig | 35 Vertretungsbonus |
| variabel / zeitbasiert | 11 Grundlohn, 632 Coaching, 256 Wazubi |
| variabel / aufgabenbasiert | 71 Schließen/Abziehen/Messen/Spülen |
| zeitabhängige Zulage | 64 Nachtschicht, 63 Samstagszulage, 61 Sonn-/Feiertagszuschlag |

(Vollständiger Katalog inkl. weiterer Lohnarten kommt aus dem Portal-Export;
für die **Demodaten** werden nur die o. g. Codes vorbefüllt.)

---

## 4. Portal-CSV → API-Mapping

Beispiel-Export (`payment_from_..._Wassermeloni.csv`, `;`-getrennt, dt. Dezimalkomma):

```
employee_no; factor; bs; cost_center; loan_type; amount
7009;        35,25;  1;  ;            21;         13,9      → Menge×Satz (bs=1)
7059;        601,69; 2;  0;           10;                   → Betrag     (bs=2)
```

| CSV | → `datev.payroll.line` | → API (`MonthRecord`) |
|---|---|---|
| `employee_no` | `employee_id` (Match Personalnr.) | `personnel_number` |
| `loan_type` | `salary_type_id` (Katalog) | `salary_type_id` |
| `factor` | `value` | `value` |
| `amount` | `factor` | `differing_factor` |
| `cost_center` | `cost_center` | `cost_center_id` |
| `bs` | `processing_key` | **— nicht in der API —** |

Beleg der Zuordnung: `factor`-Werte (z. B. 601,69) überschreiten die API-Grenze
von `differing_factor` (99,99) → müssen `value` sein; `amount` (13,9) passt in
`differing_factor`.

### ⚠️ Offene Frage: Bearbeitungsschlüssel (`bs`)
Die REST-`month-records` kennen **kein** `bs`-Feld. Hypothese: der
Bearbeitungsschlüssel ist in DATEV an der **Lohnart-Definition** hinterlegt und
muss daher nicht mitgesendet werden (die alte LODAS-ASCII-Schnittstelle führt ihn
mit, die REST-API leitet ihn aus der Lohnart ab). **Zu verifizieren** in der
Sandbox mit je einer bs=1- und bs=2-Zeile. Wir speichern `bs` in Odoo als
`processing_key` (verlustfrei fürs Review), senden ihn aber vorerst nicht.

---

## 5. Datenmodell (einheitliches Zeilenmodell)

### `datev.salary.type` — Lohnarten-Katalog & Mapping
| Feld | Typ | Zweck |
|---|---|---|
| `code` | Char | DATEV `salary_type_id` (z. B. „11") |
| `name` | Char | Klartext („Grundlohn") |
| `category` | Selection | fest_regelmäßig / fest_unregelmäßig / variabel_zeit / variabel_aufgabe / zulage_zeit |
| `channel` | Selection | `month_record` / `gross_payment` / `hourly_wage` (Default aus category, überschreibbar) |
| `external_key` | Char | optionaler Alias, falls der Import andere Schlüssel nutzt |
| `company_id` | m2o res.company | pro Mandant |
| `active` | Boolean | |

### `datev.payroll.run` — Abrechnungslauf (pro Zeitraum + Mandant)
| Feld | Typ | Zweck |
|---|---|---|
| `company_id` | m2o | Mandant |
| `reference_date` | Char/Date | Abrechnungsmonat (yyyy-MM) |
| `target_system` | Selection | Snapshot lodas/lug |
| `state` | Selection | draft → imported → validated → sent → done (+ error) |
| `line_ids` | o2m | Zeilen |
| `job_id` / `job_state` / `job_error` | | Job-Tracking wie HR |

### `datev.payroll.line` — Abrechnungszeile (einheitlich, alle Kanäle)
| Feld | Typ | Zweck |
|---|---|---|
| `run_id` | m2o | |
| `employee_id` | m2o hr.employee | Match über Personalnr. |
| `salary_type_id` | m2o datev.salary.type | liefert code/category/channel |
| `value` | Float | Menge/Betrag → `value` |
| `factor` | Float | Faktor/Satz → `differing_factor` |
| `amount` | Float | für feste Bezüge (`gross_payment`) |
| `cost_center` | Char | → `cost_center_id` |
| `processing_key` | Char | Bearbeitungsschlüssel (bs) — vorerst nur Anzeige |
| `payment_months` | Char | für `gross_payment` |
| `source` | Selection | imported / manual |
| `channel` | related | aus salary_type, steuert den Ziel-Endpoint |

Transfer gruppiert die Zeilen nach `channel` und ruft den passenden Endpoint.

---

## 6. JSON-Importformat (Vorschlag)

```json
{
  "reference_date": "2026-01",
  "client_id": "455148-1",
  "employees": [
    { "personnel_number": 7009,
      "lines": [
        { "salary_type": "21", "value": 35.25, "factor": 13.9, "processing_key": "1" },
        { "salary_type": "10", "value": 601.69, "processing_key": "2", "cost_center": "0" }
      ] } ]
}
```
- Deutsche Dezimalkommata der CSV werden beim Import zu Float geparst.
- `salary_type` wird gegen den Katalog (`code`/`external_key`) aufgelöst; unbekannte
  Codes → Zeile als „Fehler" markiert, Import läuft weiter (Review).

---

## 7. Settings (Pflicht)

- `res.company.datev_target_system` (Selection `lodas`/`lug`) — **Pflichtfeld,
  bevor irgendeine Lohn-Aktion erlaubt ist** (Guard mit klarer Fehlermeldung),
  Schalter in den company-spezifischen Connector-Einstellungen.

---

## 8. Workflow

```
JSON importieren → payroll.run (draft)
   → Zeilen prüfen/ändern/ergänzen (Review)
   → „Validieren" (Pflichtfelder, Lohnart bekannt, Mitarbeiter/Personalnr. vorhanden,
                    target_system gesetzt, value/factor in Grenzen)
   → „An DATEV übertragen" (gruppiert nach channel, async Jobs)
   → Status-Polling → done / error (mit sichtbarer Fehlermeldung)
```

---

## 9. Offene Punkte / Risiken

1. **Bearbeitungsschlüssel (`bs`)** — nicht in der REST-API (siehe §4). Sandbox-Test nötig.
2. **value/differing_factor-Semantik** — hängt an der Lohnart-Konfiguration in DATEV
   (interpretiert DATEV `value` als Betrag, Menge, Stunden? wie wirkt `differing_factor`?).
   Pro Lohnart in der Sandbox verifizieren.
3. **Payroll-Service-Freischaltung** — bei den 4 Sandbox-Mandanten aktuell **nicht**
   aktiv (nur Accounting/Beleg). Für echte Tests Mandant mit Lohn-Service nötig.
4. **LODAS vs. LuG** — Feldsätze unterscheiden sich; Umschaltung testen, sobald LuG relevant.
5. **Kostenstelle** leer vs. „0" — Bedeutung klären (CSV nutzt beides).

---

## 10. Phasenplan (Vorschlag)

- **P0 (dieser Entwurf):** Bewertung + Design. ✅
- **P1:** Katalog-Modell + `target_system`-Setting + Demodaten-Katalog (eure Codes).
- **P2:** payroll.run/line-Modelle + Views (Import-Wizard JSON, Review-Liste, editierbar).
- **P3:** Transfer-Layer `month-records` + Job-Polling; Validierungen.
- **P4:** optional `gross-payments`/`hourly-wages`; LuG-Feinschliff; später REST-Import.

Jede Phase klein, testbar, einzeln abnehmbar.
