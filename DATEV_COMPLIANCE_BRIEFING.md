# Briefing: DATEV-Schnittstellenvorgaben — Korrekturen vor der Technischen Prüfung

**Zweck dieses Dokuments:** Arbeitsauftrag für eine Claude-Code-Session. Das Repo wurde am
2026-07-08 gegen die offiziellen DATEV-Schnittstellenvorgaben auditiert. Dieses Briefing listet
alle Abweichungen mit konkreten Umsetzungsanweisungen, priorisiert nach DATEV-Relevanz
(`MUST` = ohne Umsetzung keine Freigabe, `DONT` = gefährdet die Freigabe aktiv, `SHOULD` = empfohlen).

**Arbeitsweise:** Pakete in der Reihenfolge P0 → P1 → P2 abarbeiten. Jedes Paket einzeln
committen. Bestehende Tests (`datev_connector*/tests/`) mitziehen und für neue Logik erweitern.
Odoo-17-Konventionen des Repos beibehalten. **Nicht** via SSH `odoo-bin --stop-after-init`
auf odoo.sh ausführen (siehe globale Projektregeln) — Tests lokal bzw. via CI.

---

## Quellen (verbindliche DATEV-Vorgaben)

Die Portal-Seiten sind eine Angular-SPA; Inhalte liegen hinter einer öffentlichen Strapi-API.
So lassen sich die Vorgaben maschinell nachlesen:

| Vorgabe | Browser-URL | Roh-Inhalt (JSON, Feld `body`) |
|---|---|---|
| Allgemeine Schnittstellenvorgaben | developer.datev.de/de/guides/interface-requirements | `https://developer.datev.de/mediator/strapi/guides/interface-requirements` |
| Authentifizierung (OIDC/PKCE, Token) | developer.datev.de/de/guides/authentication | `https://developer.datev.de/mediator/strapi/guides/authentication` |
| Redirect-URL-Richtlinien (ab 03/2026 Sperre!) | developer.datev.de/de/guides/new-guidelines-redirect-urls | `https://developer.datev.de/mediator/strapi/guides/new-guidelines-redirect-urls` |
| Allgemeine Fehlercodes (RFC 9457 problem+json) | developer.datev.de/de/guides/generalerrors | `https://developer.datev.de/mediator/strapi/guides/generalerrors` |
| Ablauf Cloud-Integration / Freigabeprozess | developer.datev.de/de/guides/cloud-integration-workflow | `https://developer.datev.de/mediator/strapi/guides/cloud-integration-workflow` |
| Vorgaben Kunden-Onboarding-Doku | developer.datev.de/de/guides/requirements-customer-onboarding | `https://developer.datev.de/mediator/strapi/guides/requirements-customer-onboarding` |
| Buchungsdatenservice (Datenservice + Datei) | product-detail/accounting-extf-files/2.0/documentation/interface-requirements(-file) | `https://developer.datev.de/mediator/products/accounting-extf-files?version=2.0&populate=documentation-pages` → `documentation_pages[]` |
| DATEV-Format (Zeichensatz, Struktur, Prüfprogramm) | developer.datev.de/de/file-format/details/datev-format | `https://developer.datev.de/mediator/strapi/file-formats/slug/datev-format` |
| hr:exchange Vorgaben + Beispiele | product-detail/hr-exchange/1.0.0/documentation/interface-requirements | `https://developer.datev.de/mediator/products/hr-exchange?version=1.0.0&populate=documentation-pages` |
| OpenAPI accounting:extf-files | — | `https://developer.datev.de/mediator/apis/4e42f72c-302f-4fb0-b097-ac157c32731a/document` |
| OpenAPI hr:exchange | — | `https://developer.datev.de/mediator/apis/2099de9d-97c8-4e11-a0c0-0a435e197973/document` |
| OIDC Discovery (prod / sandbox) | — | `https://login.datev.de/openid/.well-known/openid-configuration` bzw. `.../openidsandbox/...` |

Verifizierte Fakten aus den Discovery-/OpenAPI-Dokumenten (Stand 2026-07-08):
- Revocation-Endpoint prod: `https://api.datev.de/revoke`, sandbox: `https://sandbox-api.datev.de/revoke`
- UserInfo-Endpoint prod: `https://api.datev.de/userinfo`, sandbox: `https://sandbox-api.datev.de/userinfo`
- Scope-Namen korrekt wie im Code: `datev:accounting:extf-files-import`, `datev:hr:payrolldataexchange`
- EXTF `Filename`-Header-Pattern: `EXTF_.{0,51}\.csv`; Job-`result`-Enum: `pending|succeeded|failed`
- hr:exchange: `reference-date` = `yyyy-MM` (Query), Header `Target-System: lodas|lug`, `X-Datev-Client-ID` — wie im Code

---

## P0 — Blocker (MUST, ohne diese scheitert bereits die Sandbox-Freigabe)

### P0.1 EXTF-Formatversion mindestens 12 (aktuell 9)
**Vorgabe (Buchungsdatenservice, Datei):** „MUST: Conversion of the DATEV-Format with at least
main version 700, format versions **12** for posting batches and 5 for customers/vendors."
Das aktuelle Portal-Beispiel nutzt Version **13**.

**Datei:** `datev_connector_accounting/services/extf_generator.py`
- `_FORMAT_VERSION = 9` → auf **13** heben (mind. 12).
- Spaltenliste `_COLUMNS` auf die v13-Spaltenüberschriften aktualisieren (125 Spalten; u. a.
  `"EU-Land u. UStID (Bestimmung)"`, `"EU-Steuersatz (Bestimmung)"`, `"Kost-Menge"`, `"BVV-Position"`,
  neue letzte Spalte `"Abw. Skontokonto"`). Referenz: Beispieldatei in der Seite „Getting started"
  des DATEV-Format-Guides (Strapi-URL oben) — die dortige Spaltenzeile 1:1 übernehmen.
- Headerzeile (Zeile 1) auf die vollständige 31-Feld-Struktur bringen, siehe P0.4.

### P0.2 Zeichensatz der EXTF-Datei
**Vorgabe (DATEV-Format, „Character set"):** Standard ist ISO-8859-1/CP1252. Unicode (UTF-8/16/32)
wird **nur mit ByteOrderMark** akzeptiert und nur beim Import via Rechnungswesen/online-API.

**Datei:** `extf_generator.py`, `generate()` gibt aktuell `content.encode("utf-8")` **ohne BOM** zurück → nicht spezifikationskonform.
- Umstellen auf `content.encode("cp1252", errors="replace")` (sicherste Variante, auch fürs
  DATEV-Prüfprogramm, das kein Unicode kann). Alternative UTF-8 **mit** BOM (`utf-8-sig`) ist zulässig,
  aber CP1252 ist für die Dateiprüfung (Pflichttermin „Technical review - file format") die robustere Wahl.
- Test ergänzen: Umlaute/ß im Buchungstext überleben Roundtrip; keine `\n`/`\r` in Textfeldern.

### P0.3 Quoting der Datenzeilen
**Vorgabe (DATEV-Format, „Getting started"):** Textfelder **müssen** in doppelte Anführungszeichen,
Anführungszeichen im Text verdoppelt, Zahlen (Umsatz, Konto, …) **unquoted** mit Dezimal-Komma,
jede Zeile endet mit CR/LF.

**Datei:** `extf_generator.py`, `generate()`/`_write_move()`: `csv.writer(QUOTE_MINIMAL)` quotet
praktisch nichts → Verstoß.
- Zeilen manuell schreiben (wie schon beim Header) oder pro Spalte typisieren: Text-Spalten
  (Soll/Haben-Kz, WKZ, Belegfeld 1/2, Buchungstext, Beleglink, …) immer quoten; numerische
  Spalten (Umsatz, Konto, Gegenkonto, Belegdatum, …) nie quoten; leere Felder je nach Typ.
  Orientierung: die Beispiel-Datenzeilen im „Getting started"-Guide.

### P0.4 EXTF-Header vervollständigen
**Datei:** `extf_generator.py`, `_write_header()`:
- **Feld 6 „Erzeugt am"**: aktuell leer → mit `YYYYMMDDHHMMSSFFF` (17 Stellen, jetzt-Zeitstempel) füllen
  (das Portal-Beispiel liefert es gefüllt; leer riskiert Header-Validierungsfehler).
- **Feld 17 „Bezeichnung"**: aktuell leer → befüllen (z. B. `"Odoo Buchungsstapel <von>-<bis>"`).
  Für die Musterdateien der Dateiprüfung MUSS hier der jeweilige Use Case stehen (siehe P2.3).
- **Feld 21 „Festschreibung"**: aktuell `0` → **konfigurierbar machen, Default `1`** (GoBD-Erwartung;
  Prüfer fragen danach). Neues Setting `datev_extf_festschreibung` auf `res.company` + Settings-View.
- Headerlänge/Reihenfolge gegen das v13-Beispiel abgleichen (31 Felder inkl. Sachkontenrahmen-Feld).
- **Validierung ergänzen:** Export abbrechen, wenn `date_from`/`date_to` nicht im selben
  Wirtschaftsjahr liegen (Belegdatum ist `DDMM` ohne Jahr — Stapel darf kein WJ überspannen).

### P0.5 Buchungslogik: doppelte Beträge durch Zeilen-Spiegelung
**Vorgabe:** „MUST: The transferred transaction and master data must be read and processed
**without errors** in DATEV Accounting." Fachlich falsche Stapel fallen in der Prüfung durch.

**Datei:** `extf_generator.py`, `_write_move()`: Aktuell wird **jede** Move-Line als eigene
Buchungszeile mit geratenem Gegenkonto exportiert. Eine einfache Ausgangsrechnung
(Debitor 119 S / Erlös 100 H / USt 19 H) erzeugt so **drei** Buchungszeilen → der Umsatz wird
doppelt gebucht.
- Umbauen auf Pivot-Logik: Pro Move die Pivot-Zeile bestimmen (Debitor-/Kreditor-Zeile bzw.
  betragsgrößte Zeile), **nur die Nicht-Pivot-Zeilen** exportieren, `Gegenkonto` = Pivot-Konto,
  Soll/Haben-Kz aus Sicht der exportierten Zeile.
- **BU-Schlüssel/Steuer klären:** Entweder (a) Netto-Einzelzeilen inkl. separater Steuerzeilen auf
  nicht-automatische Konten (dann Steuerkonten-Mapping dokumentieren) oder (b) Brutto-Zeile mit
  BU-Schlüssel (Spalte 9) je Steuersatz. Variante (b) ist der DATEV-Normalfall — dafür
  `datev.account.mapping` um ein optionales Feld `datev_bu_key` bzw. ein Tax-Mapping-Modell erweitern.
  Entscheidung im Code dokumentieren; die gewählte Logik muss beim Prüftermin erklärt werden.
- **Fremdwährung (Felder 3–6):** Aktuell wird `move.currency_id.name` gesetzt, aber weder `Kurs`
  noch `Basis-Umsatz`. Entweder sauber implementieren (Umsatz in Fremdwährung, Kurs, Basis-Umsatz
  EUR, WKZ Basis-Umsatz) oder Nicht-EUR-Moves mit klarer `UserError` ablehnen. Halb ist schlimmer als gar nicht.
- **Belegfeld 1** (`_write_move`, `row[10]`): Kürzung auf 12 Zeichen ist die alte Grenze — v700
  erlaubt 36 Zeichen. Auf 36 erweitern, unerlaubte Zeichen filtern (`$ & % * + - /` sind erlaubt).

### P0.6 OAuth: Pflichtparameter `nonce` fehlt
**Vorgabe (Auth-Guide):** „Nonce Parameter: **Required** parameter with a minimum length of 20
characters." + Schnittstellenvorgaben-MUST: `code_challenge`/`code_verifier`/`nonce` je Request neu.

**Datei:** `datev_connector/services/datev_api.py`, `get_authorization_url()`:
- `nonce = secrets.token_urlsafe(24)` erzeugen, als Parameter mitsenden, zusammen mit state/verifier
  ablegen (siehe P0.7). Optional (SHOULD): ID-Token-nonce-Claim nach dem Code-Austausch verifizieren.
- Ebenfalls empfohlen (Auth-Guide): `enableWindowsSso=true` an die Authorize-URL anhängen.

### P0.7 OAuth: State/PKCE-Ablage global + Multi-Company-Bug
**Problem:** `get_authorization_url()` speichert `state` und `code_verifier` in
`ir.config_parameter` (global, ein Slot für die ganze Instanz):
1. Zwei parallele Connect-Vorgänge (oder zwei Companies) überschreiben sich gegenseitig.
2. Der Callback (`controllers/oauth.py`) nimmt `request.env.company` — das ist nicht zwingend die
   Company, für die der Flow gestartet wurde.
3. `state` wird nach Gebrauch nicht invalidiert (nur der Verifier wird geleert).

**Fix:**
- Flow-Daten pro Vorgang persistieren, z. B. transientes Modell `datev.oauth.flow`
  (`state` (unique), `nonce`, `code_verifier`, `company_id`, `user_id`, `create_date`) oder
  `request.session`. Im Callback per `state` nachschlagen, Company daraus übernehmen,
  Datensatz sofort löschen (single-use), Einträge > 10 min verwerfen.
- `datev.token`-Erzeugung im Callback läuft ohne sudo → für Nicht-Admins `AccessError`
  (ir.model.access erlaubt nur `base.group_system`). `_get_or_create` im Controller mit `sudo()` aufrufen.

### P0.8 Token-Handling: Single-Use-Refresh-Token nicht abgesichert
**Vorgabe (Auth-Guide):** Refresh-Tokens sind **single-use**; Doppeleinlösung invalidiert die
gesamte Session. Odoo läuft multi-worker (Cron + Benutzer parallel) → aktuell kann
`get_valid_access_token()` denselben RT zweimal einlösen.

**Datei:** `datev_connector/models/datev_token.py`:
- `refresh_access_token()` mit Row-Lock serialisieren: in einer eigenen Transaktion
  `SELECT ... FOR UPDATE` auf die Token-Zeile (`self.env.cr.execute("SELECT id FROM datev_token WHERE id=%s FOR UPDATE", ...)`),
  nach Lock-Erhalt Token neu lesen — wenn inzwischen gültig, kein Refresh. Neues AT/RT sofort
  committen (eigener Cursor via `self.pool.cursor()`), damit ein späterer Rollback der
  Business-Transaktion das bereits eingelöste RT nicht verwirft.
- Tote/falsche Konstanten `DATEV_AUTH_URL_SANDBOX`/`DATEV_TOKEN_URL_*` (Zeilen 9–12,
  `login.sandbox.datev.de` existiert nicht) löschen — Endpoints kommen aus `datev_api.py`.

### P0.9 Token-Revocation implementieren (Disconnect = /revoke)
**Vorgabe (MUST):** „RT can be deleted via a button …, i.e. deletion in the 3rd party app **and
/revoke call to DATEV**." `token_type_hint` ist bei DATEV **Pflicht** (RFC 7009).

**Dateien:** `datev_api.py` + `datev_token.py`:
- Neue Methode `revoke_token(token, token_type_hint)` → `POST https://api.datev.de/revoke`
  (sandbox: `https://sandbox-api.datev.de/revoke`), Basic-Auth mit Client-ID/Secret, Form-Body
  `token=...&token_type_hint=access_token|refresh_token`.
- `action_disconnect()` ruft **zwei** Revokes (AT + RT) auf, bevor die Felder geleert werden;
  Fehler beim Revoke loggen, Disconnect trotzdem durchführen.

### P0.10 hr:exchange: Pflicht-Workflow einhalten (Auth-Check, Read-before-Write, Result-Abruf)
**Vorgaben (hr:exchange Interface Requirements):**
- „MUST: Perform the authorization check" (`GET /clients/{client-id}`) — fehlt komplett.
- „MUST: Before any later creation or modification … a complete read is required" — fehlt:
  `_push_employee_to_datev()` postet blind.
- „MUST: After every creation or modification, a GET job must be performed to verify data
  persistence" + Result-Body kann trotz `state=successful` `errors[]` enthalten und liefert die
  ggf. automatisch vergebene `personnel_number` — der Result-Abruf
  (`GET /jobs/{uuid}/result[/employees]`) fehlt komplett.

**Dateien:** `datev_connector/services/datev_api.py`, `datev_connector_hr/models/hr_employee.py`:
- `hr_exchange_get_client(client_id)` (`GET /clients/{client-id}`) ergänzen; vor jedem Sync und
  in einem neuen Settings-/Wizard-Button „Verbindung prüfen" aufrufen; Ergebnis dem Benutzer anzeigen.
- Fetch-Flow implementieren: `POST /clients/{id}/jobs` (Body mit Ressource `employees`),
  Polling (P1.2-Kadenz), `GET .../result/employees`. Vor einem Create prüfen, ob die
  Personalnummer in DATEV existiert → dann PUT statt POST; `datev_sync_created` aus dem
  Fetch-Ergebnis ableiten statt (wie jetzt) beim ersten POST blind auf `True` zu setzen.
- Nach Job-Erfolg `GET .../result` abrufen, `errors[]` auswerten (nur bei leerem errors → succeeded),
  zurückgegebene `personnel_number` speichern.
- `datev_sync_created=True` erst **nach** verifiziertem Erfolg setzen; bei Fehlschlag zurücksetzen,
  sonst läuft der nächste Sync als PUT gegen einen nie angelegten Mitarbeiter.

---

## P1 — Pflicht für die Freigabe (MUST/DONT, aber nicht dateiformat-blockierend)

### P1.1 Technisches HTTP-Log (MUST, gilt für ALLE Module)
**Vorgabe:** Chronologisches Log aller Requests an das DATEV-Gateway, **mind. 14 Tage** Aufbewahrung.
Pro Request: Timestamp (hh:mm:ss), Methode + volle URL inkl. Query, Header **ohne Authorization**;
pro Response: Timestamp, HTTP-Code, Header mind. `X-Global-Transaction-ID` und `V-Cap-Request-ID`,
Body nur bei Fehlern/Statusabfragen. Beim Prüftermin wird das Log live gezeigt.

**Umsetzung:**
- Neues Modell `datev.api.log` in `datev_connector` (Felder: `request_ts`, `method`, `url`,
  `request_headers` (Text, Authorization + X-DATEV-Client-Secret geschwärzt), `response_ts`,
  `status_code`, `x_global_transaction_id`, `v_cap_request_id`, `response_body` (nur bei
  status >= 400 oder Statusabfragen), `company_id`). List-View chronologisch, Menüpunkt unter
  DATEV → Technik, Zugriff `base.group_system`.
- **Alle** HTTP-Aufrufe durch einen zentralen Pfad leiten: `DatevApiService._request()` loggt;
  die Streuner umziehen: `extf_import()` und `extf_job_status()` (datev_api.py) sowie der
  Raw-`requests.get` in `res_config_settings.action_datev_fetch_clients()`.
- Cron „DATEV: Alte API-Logs löschen" (täglich, löscht > 30 Tage — nicht < 14!).
- In `extf_import()` den irreführenden Platzhalter-Header-Dict (`"Authorization": "Bearer <token>"`,
  `"X-DATEV-Client-Secret": "<secret>"`) aufräumen — echte Header bauen, im Log schwärzen.

### P1.2 Job-Polling begrenzen (DONT 24/7-Polling; hr:exchange-Poll-Kadenz ist MUST)
**Vorgaben:** hr:exchange: erste Abfrage frühestens nach 60 s, max. 1 Abfrage/min, **Abbruch nach
15 min** ohne Statuswechsel (als Fehler dokumentieren). EXTF: `Retry-After`-Header respektieren
(SHOULD). Allgemein: kein Dauer-Polling (DONT), Fehlerquote < 10 % (MUST).

**Dateien:** `datev_connector_accounting/models/account_move.py`,
`datev_connector_hr/models/hr_employee.py`, beide `ir_cron.xml`:
- Felder ergänzen: `datev_job_created_at`, `datev_job_last_poll` (beide Module).
- Cron-Logik: nur Jobs pollen mit `now - created_at >= 60s` und `now - last_poll >= 60s`;
  Jobs mit `now - created_at > 15 min` (HR) bzw. > 24 h (EXTF, großzügiger da DATEV-Verarbeitung
  dauern kann — im Zweifel beim Prüftermin nachfragen) auf `failed` mit Meldung
  „Zeitüberschreitung — Status unbekannt, bitte manuell prüfen" setzen.
- Manuelle Refresh-Buttons (`action_datev_refresh_job_status` in beiden Modulen) gegen
  Spam schützen (Mindestabstand 60 s, sonst freundliche Meldung).
- EXTF-Upload: `Retry-After` aus der 202-Response speichern und als frühesten Poll-Zeitpunkt verwenden.
- `extf_job_status()`: 404 nicht endlos als `pending` werten (fällt sonst unters 15-min/24-h-Limit, ok,
  aber im Log als Auffälligkeit kennzeichnen).
- `account_move._poll_datev_jobs()`: Config wird ohne Company geholt
  (`_get_datev_config()` → `env.company`) — nach `move.company_id` gruppieren und je Company
  den richtigen Token/Service verwenden (Multi-Company-Bug).

### P1.3 Berechtigungsprüfung Buchungsdatenservice sichtbar machen (MUST)
**Vorgabe:** Vor Datentransfer muss über `GET /clients` bzw. `GET /clients/{client-id}`
(accounting-clients v2) geprüft werden, ob der Mandant den **Buchungsdatenservice** hat; erst nach
bestätigtem Check darf die Verbindung als „erfolgreich" angezeigt werden. Bei Nutzung der
Listen-Variante: scrollbare Anzeige (Paging) mit Firmenname + Berater-/Mandantennummer.

**Datei:** `datev_connector/models/res_config_settings.py`:
- `action_datev_fetch_clients()` von der Sticky-Notification auf einen echten Auswahldialog
  umbauen (transientes Modell mit Liste: Name, Beraternummer, Mandantennummer, Services;
  Auswahl übernimmt die Nummern in die Company). Paging beachten (`top`/`skip`, max. 100).
- Neuer Button „Mandant prüfen": `GET /clients/{consultant}-{client}`; Ergebnis (Firma + Services)
  anzeigen; `services` muss den Buchungsdatenservice enthalten, sonst Warnung.
- Der Verbindungsstatus in den Settings sollte erst dann vollständig „grün" sein, wenn Token
  **und** Mandantenprüfung ok sind (z. B. dritter Status „verbunden, Mandant ungeprüft").
- Analog für HR: Prüfung gegen `hr-exchange /clients/{client-id}` (siehe P0.10).

### P1.4 UI-Pflichtangaben zur Verbindung (MUST)
**Vorgabe (Auth-Block der Schnittstellenvorgaben):**
- Ablaufdatum des **Refresh-Tokens** sichtbar (Format mind. `DD.MM.YYYY HH:MM`).
- **Voller Name** der Person, die das Token ausgestellt hat (UserInfo-Endpoint) sichtbar.
- Link auf die DATEV-App „Verbundene Anwendungen" `https://apps.datev.de/tokrevui`.

**Umsetzung:**
- `datev.token`: Felder `refresh_token_expiry` (= Zeitpunkt der **ersten** AT-Ausstellung + 11 h;
  bei jedem Connect neu, bei Refresh **nicht** verlängern) und `issued_by_name` ergänzen.
- Nach erfolgreichem Code-Austausch `GET userinfo` (prod `https://api.datev.de/userinfo`,
  sandbox `https://sandbox-api.datev.de/userinfo`, Bearer-AT) → `given_name family_name` speichern
  (Scope `profile` wird bereits angefragt).
- Settings-View + `datev_token_views.xml`: beide Felder anzeigen; statischen Link/Hinweis auf
  `https://apps.datev.de/tokrevui` („Token in DATEV verwalten/widerrufen") einbauen.

### P1.5 Scopes minimal & vom Kunden aktiv gewählt (MUST)
**Vorgabe:** Nur Scopes anfragen, die der Kunde für die gewünschten Datenservices braucht; bei
mehreren Datenservices in einem Token muss der Kunde die Nutzung **aktiv auswählen** (UI).

**Dateien:** `datev_api.py` (`_SCOPE` hardcodet accounting **und** hr), `res_company.py`,
`res_config_settings*.xml`:
- Company-Flags `datev_service_accounting` / `datev_service_hr` (Checkboxen in den Settings,
  Default: nur wenn das jeweilige Modul installiert ist; Beschriftung mit den offiziellen
  Datenservice-Namen „DATEV Buchungsdatenservice", „DATEV Lohnaustauschdatenservice").
- Scope-String dynamisch bauen: immer `openid profile`; `datev:accounting:extf-files-import`
  + `datev:accounting:clients` nur bei Accounting; `datev:hr:payrolldataexchange` nur bei HR.
  Nach dem Connect die tatsächlich gewährten Scopes (Feld `scope` am Token) anzeigen.
- Hinweis in Settings-Hilfetexten: Der jeweilige Datenservice muss beim Steuerberater/DATEV
  **bestellt und aktiviert** sein, mit Link `http://go.datev.de/datenservices-einrichten`
  (Onboarding-Vorgabe, siehe Guide „requirements-customer-onboarding").

### P1.6 4XX-Fehlerbehandlung mit DATEV-Hilfe-URLs (MUST)
**Vorgabe:** Alle 4XX-Fehler behandeln; die in der `application/problem+json`-Antwort (RFC 9457)
enthaltenen Infos/Hilfe-URLs müssen dem Benutzer angezeigt werden.

**Datei:** `datev_api.py`, `_request()`/`extf_import()`/`_token_request()`:
- Zentralen Parser bauen: bei 4XX/5XX `title`, `detail` und enthaltene URLs aus dem
  problem+json extrahieren und in die `UserError`-Meldung übernehmen (statt rohem `resp.text`).
  401 mit `invalid_token` → verständliche Meldung „Bitte neu mit DATEV verbinden".
- Fehlermeldungen dürfen niemals Token/Secret-Werte enthalten.

### P1.7 Re-Export nach fehlgeschlagenem Job ermöglichen (MUST)
**Vorgabe (Buchungsdatenservice):** Doppelübertragung normal verhindern ✔ (Flag existiert), aber
für Support-Fälle muss eine erneute Übertragung möglich sein, und ein fehlgeschlagener Upload darf
nicht dauerhaft als „exportiert" gelten.

**Dateien:** `datev_export_wizard.py`, `account_move.py`:
- Beim Job-Ausgang `failed`: `datev_exported` zurücksetzen (oder Button „Erneut exportieren"
  auf fehlgeschlagenen Moves), damit der Standard-Flow sie wieder findet.
  `include_exported`-Checkbox als Support-Override beibehalten.

### P1.8 Sensible Daten härten (MUST „verschlüsselt", DONT „nicht anzeigen/loggen")
- `res.company.datev_client_secret` ist für alle internen Benutzer lesbar (ORM-Read auf
  res.company). Feld-Level-Schutz: `groups="base.group_system"` auf die Felder
  `datev_client_secret` (und sinnvollerweise `datev_client_id`) in `res_company.py` und den
  related-Feldern in `res_config_settings.py`.
- Access-/Refresh-Token: bleiben in `datev.token` (nur `base.group_system` ✔). Zusätzlich
  sicherstellen, dass sie in **keiner** View und **keinem** Log auftauchen (aktuell ok — Views
  zeigen nur expiry/scope; `_logger`-Aufrufe prüfen). Im HTTP-Log schwärzen (P1.1).
- Verschlüsselung at rest: mindestens dokumentieren, dass DB-/Filestore-Verschlüsselung
  (odoo.sh: Volume-Encryption) das MUST abdeckt; optional Fernet-Verschlüsselung der
  Token-Felder mit Key aus `odoo.conf` implementieren.

### P1.9 Redirect-URL-Konformität absichern (MUST, Sperre ab 01.03.2026)
**Vorgabe:** Confidential Clients in Produktion: **nur HTTPS**, kein localhost, keine IPs, keine
Custom-Schemes. Ab 01.03.2026 werden Apps mit unzulässigen Redirect-URLs **gesperrt**.

**Datei:** `res_config_settings.py`, `action_datev_connect()`:
- Guard: wenn `datev_sandbox_mode == False` und `web.base.url` nicht `https://` oder
  localhost/IP → `UserError` mit Erklärung. Redirect-URL in den Settings anzeigen
  (readonly), damit der Benutzer weiß, was er im Developer Portal eintragen muss.
- README: Hinweis, dass die produktive App im Developer Portal exakt
  `https://<domain>/web/datev/oauth/callback` registriert haben muss.

### P1.10 HR-Sync-Verhalten glätten (Economy-MUST / Effizienz)
**Datei:** `datev_connector_hr/models/hr_employee.py`:
- `write()`-Trigger löst pro Speichern einen Sync aus; bei Mehrfach-Änderungen in kurzer Folge
  entstehen viele Jobs. Debounce einbauen: `datev_sync_dirty`-Flag setzen und einen
  Sammel-Cron (z. B. alle 5 min, nur wenn dirty-Records existieren) übertragen lassen — oder
  mindestens mehrere gleichzeitig geänderte Mitarbeiter in **einem** POST bündeln
  (API akzeptiert Listen; aktuell Einzel-Requests pro Mitarbeiter).
- Der automatische Sync bleibt zulässig (kundengetriggert/regelbasiert), das beim Prüftermin so erklären.

---

## P2 — Vorbereitung Prüftermin & SHOULD-Punkte

### P2.1 Belegbilderservice + Beleglink (für „Buchungsdatenservice inkl. Belegbild"-Abnahme)
Die Produktionsabnahme prüft: „MUST: The document linked to an invoice record must be displayed
in DATEV Accounting." Wenn Belegverknüpfung Teil des beworbenen Funktionsumfangs ist
(README verspricht „digital voucher linking"!), muss implementiert werden:
- Upload je Beleg: `PUT https://accounting-documents.api.datev.de/platform/v2/clients/{client-id}/documents/{guid}`
  (GUID RFC4122, von Odoo erzeugt → verhindert Doppel-Uploads), Scope `datev:accounting:documents` ergänzen (P1.5-Auswahl).
- Metadata-JSON-Objekt mit **allen drei** Pflichtfeldern `category` (z. B. „Odoo"), `folder`
  (Belegart), `register` (Monat `YYYY-MM`) — MUST.
- In der EXTF-Zeile Spalte 20 `Beleglink` = `BEDI "<guid>"` setzen.
- Reihenfolge: erst Belege, dann EXTF-Datei.
- **Alternativ** (wenn Aufwand zu hoch): Belegverknüpfung aus README/Funktionsumfang streichen
  und beim Prüftermin nur Buchungsdaten ohne Belege anmelden. Nicht Halbes präsentieren.

### P2.2 Payroll-Modul: LODAS-ASCII-Generator entfernen oder konform machen
`datev_connector_payroll/services/lodas_generator.py` erzeugt ein Fantasieformat
(`[Allgemein]/Personalnummer=...`), das keiner DATEV-Spezifikation entspricht (echtes
LODAS-ASCII braucht u. a. `Ziel=LODAS`, `[Satzbeschreibung]`, Satzarten). Ein Prüfer, der das
sieht, lehnt ab.
- **Empfehlung:** Generator + zugehörige Wizard-Pfade/Tests entfernen (der Transfer läuft laut
  `DESIGN.md` ohnehin künftig über hr:exchange `month-records`). Falls ASCII-Dateiexport
  (Lohnimportdatenservice) gewünscht bleibt: separate Pflicht-Dateiprüfung bei DATEV einplanen
  und exakt nach hr-imports-Spezifikation neu implementieren.
- Beim späteren P3-Transfer (month-records) gelten dieselben hr:exchange-MUSTs wie in P0.10/P1.2
  (Read-before-Write: vorhandene Monatswerte prüfen; Änderungen = Storno mit negativem Wert + Neuerfassung).

### P2.3 Musterdateien & Prüfprogramm (Pflichttermin Dateiprüfung)
- Dev-Hilfe (z. B. `dev/generate_sample_files.py` oder Wizard-Option) bauen, die auf Basis der
  DATEV-Musterbelege (`https://developer.datev.de/assets/Musterbelege_1514b3d255.zip`) je Use Case
  eine EXTF-Datei erzeugt (Ausgangs-/Eingangsrechnungen, Gutschrift/Rechnungskorrektur,
  Generalumkehr; je Sonderfall min. 3 Datensätze). Use Case in Header-Feld 17 eintragen (P0.4).
- Alle erzeugten Dateien mit dem DATEV-Format-Prüfprogramm validieren
  (`https://developer.datev.de/assets/Datev_Format_Pruefprogramm_2_2_3_0_76439824cb.zip`, Windows).
  Ergebnis als Checkliste in `dev/` dokumentieren.

### P2.4 Architektur- & Rollen-Erklärung für den Prüftermin (MUST „outline")
Kurzes Dokument `dev/RELEASE_MEETING_NOTES.md` anlegen:
- Architektur: Webserver-Integration (Odoo-Server hält API-Client & Tokens zentral; Redirect-URL
  HTTPS; Kommunikation nur vom Odoo-Host).
- Entitäten-Mapping: Odoo `res.company` ↔ DATEV Mandant (`{Beraternr}-{Mandantennr}`), Token pro
  Company, Zugriff auf Token/Secret nur `base.group_system`; HR-Daten zusätzlich `hr.group_hr_user`.
- Support-Konzept: First-Level durch Aquarius Ventures, Log-Einsicht via `datev.api.log`,
  DATEV-Ticket nur durch uns (nicht Kunden zu DATEV schicken — DONT).
- Fehlerquoten-Monitoring: Auswertung über `datev.api.log` (Anteil 4XX/5XX), Ziel < 10 %.

### P2.5 Kleinkram
- `datev_connector_accounting/services/extf_parser.py`: dekodiert nur UTF-8 — auch CP1252
  akzeptieren (DATEV-Exporte sind i. d. R. CP1252): erst `utf-8-sig` versuchen, dann `cp1252`.
- `__pycache__`-Verzeichnisse/`.pyc` aus dem Repo entfernen und `.gitignore` prüfen.
- README: Datenservice-Namen korrekt führen („DATEV Buchungsdatenservice",
  „DATEV Lohnaustauschdatenservice (hr:exchange)"), DATEV immer in Großbuchstaben,
  Onboarding-Hinweis + Link `go.datev.de/datenservices-einrichten` (P1.5).
- Wenn `offline_access`/Langzeit-Token **nicht** genutzt wird (aktuell nicht): sicherstellen, dass
  es auch nirgends angefragt wird (ist ok) — dann gelten die Kurzzeit-Token-Regeln (11 h), d. h.
  Cron-Polling schlägt nach RT-Ablauf fehl → saubere Meldung „Bitte neu verbinden" statt
  Fehler-Spam (max. 1 Fehlversuch, dann Token-State auf `disconnected` + `datev_last_error` setzen;
  wichtig für die < 10 %-Fehlerquote).

---

## Abnahme-Checkliste (Selbsttest vor dem DATEV-Termin)

- [ ] Authorize-Request enthält `state` (≥20), `nonce` (≥20), PKCE S256, je Request neu
- [ ] Token-Austausch via Basic-Auth ✔ (bereits ok)
- [ ] RT wird nie doppelt eingelöst (Parallel-Test: Cron + UI gleichzeitig)
- [ ] Disconnect ruft `/revoke` für AT **und** RT mit `token_type_hint`
- [ ] Settings zeigen: Ampel-Status, RT-Ablauf (DD.MM.YYYY HH:MM), Aussteller-Name, tokrevui-Link
- [ ] Scope-Anfrage entspricht exakt den aktivierten Datenservices
- [ ] Mandanten-Check (accounting-clients bzw. hr-exchange GET /clients/{id}) vor „verbunden"
- [ ] EXTF: Version 700/13, CP1252, Textfelder gequotet, CRLF, Erzeugt-am gefüllt,
      Festschreibung konfigurierbar (Default 1), WJ-Validierung, Prüfprogramm grün
- [ ] Fachlicher Test: Musterrechnung Odoo → DATEV Rechnungswesen fehlerfrei einlesbar
- [ ] Job-Polling: Erstabfrage ≥ Retry-After/60 s, ≤ 1/min, Abbruch nach Limit, kein Endlos-Polling
- [ ] HR: Fetch vor Write, Result-Abruf nach Job, 409-Handling bei doppelter Personalnummer
- [ ] `datev.api.log` zeigt lückenlose Chronologie inkl. X-Global-Transaction-ID / V-Cap-Request-ID,
      ohne Authorization-Header, ≥ 14 Tage
- [ ] 4XX-Fehler zeigen DATEV-title/detail/Hilfe-URL im UI
- [ ] Prod-Modus verweigert Connect bei Nicht-HTTPS-`web.base.url`
- [ ] Keine Secrets/Tokens in UI (außer maskiertem Secret-Eingabefeld), Logs oder Fehlermeldungen
