# DATEV Release-Meeting — Architektur- und Konzeptnotizen

Vorbereitung auf die Freigabetermine (Sandbox-/Produktionsfreigabe) des
Odoo DATEV Cloud Connectors. Die Punkte entsprechen den MUST-Anforderungen
„Architecture“, „Rights & roles“ und „Support“ der allgemeinen
Schnittstellenvorgaben.

## Architektur: Webserver-Integration

- Der Odoo-Server (odoo.sh bzw. eigene HTTPS-Domain des Kunden) ist der
  zentrale Webserver. Er hält den API-Client (Client-ID/Secret) und alle
  Tokens; **sämtliche** Kommunikation mit dem DATEV API-Gateway geht vom
  Odoo-Host aus. Es gibt keine Desktop-/Mobile-Komponente, die direkt mit
  DATEV spricht.
- OAuth: Authorization Code Flow (Confidential Client) mit PKCE S256 und
  nonce, `client_secret_basic` am Token-Endpoint. Redirect-URL:
  `https://<domain>/web/datev/oauth/callback` (nur HTTPS; im Developer
  Portal exakt registriert). Der `state`-Parameter identifiziert den
  laufenden Vorgang (Modell `datev.oauth.flow`, single-use, 10 min TTL)
  und ordnet den Callback der richtigen Odoo-Company zu.
- Kurzzeit-Refresh-Token (11 h), kein `offline_access`. Refresh-Tokens
  sind single-use; Refreshes sind serverseitig durch Row-Locks
  serialisiert (kein Doppel-Einlösen durch Cron + Benutzer).

## Entitäten-Mapping / Rechte & Rollen

- Odoo `res.company` ⟷ DATEV Mandant (`{Beraternummer}-{Mandantennummer}`).
  Genau ein Token pro Company (`datev.token`, SQL-Unique).
- Zugriff auf Token und Client-Secret: nur `base.group_system`
  (Feld-Level-Groups + Modell-ACL). Buchhalter (account.group_account_user)
  können Exporte auslösen, sehen aber keine Credentials; HR-Daten
  zusätzlich durch `hr.group_hr_user` geschützt.
- Vor jedem Datentransfer Berechtigungsprüfung:
  - Buchungsdatenservice: `GET accounting-clients /clients/{id}` („Mandant
    prüfen“-Button; Verbindungsstatus wird erst danach vollständig grün).
  - hr:exchange: `GET /clients/{id}` vor jedem Sync-Zyklus.

## Fachlicher Ablauf

- **Buchungsdaten:** EXTF v700/13, CP1252, Pivot-Buchungslogik
  (Gegenkonto = Debitor-/Kreditorkonto). Steuer: Brutto-Zeilen mit
  BU-Schlüssel aus `datev.tax.mapping` (DATEV-Normalfall); ohne
  vollständiges Mapping Netto-Einzelzeilen inkl. Steuerzeilen auf
  nicht-automatische Konten (Fallback, dokumentiert im Generator).
  Upload asynchron; Doppelübertragung durch `datev_exported`-Flag
  verhindert, fehlgeschlagene Jobs setzen das Flag zurück (Re-Export für
  Supportfälle möglich).
- **Personalstammdaten:** Pflicht-Workflow fetch → push → result
  (Read-before-Write; `datev_sync_created` wird erst nach verifiziertem
  Ergebnis gesetzt). Automatischer Sync ist kundengetriggert/regelbasiert:
  Feldänderungen setzen nur ein Dirty-Flag, ein 5-Minuten-Cron bündelt die
  Übertragung.
- **Job-Polling:** Erstabfrage ≥ 60 s (bzw. Retry-After), max. 1/min,
  Timeout 15 min (HR) / 24 h (EXTF) mit klarer Fehlermeldung — kein
  24/7-Polling.

## Support-Konzept

- First-Level-Support durch Aquarius Ventures (muri@aquariusventures.net).
- Technisches HTTP-Log: Modell `datev.api.log` (Menü DATEV → Technik),
  chronologisch, Authorization/Secret geschwärzt, inkl.
  X-Global-Transaction-ID und V-Cap-Request-ID, Aufbewahrung 30 Tage
  (Vorgabe: ≥ 14). Wird beim Prüftermin live gezeigt.
- DATEV-Tickets ausschließlich durch uns
  (terminland.de/datev_schnittstellenberatung) — Kunden werden nicht an
  DATEV oder DATEV-Mitglieder verwiesen.
- Fehlerquoten-Monitoring: Auswertung von `datev.api.log`
  (Filter „Fehler (4XX/5XX)“); Ziel < 10 % nach Produktionsfreigabe.
  Abgelaufene Verbindungen werden nach einem Fehlversuch getrennt
  (kein Retry-Spam).

## Sensible Daten

- Client-Secret & Tokens: nie in UI/Logs/Fehlermeldungen; Feld-Groups
  `base.group_system`; HTTP-Log schwärzt Authorization und
  X-DATEV-Client-Secret.
- Verschlüsselung at rest: odoo.sh Volume-Encryption (bzw. beim
  Selbst-Hosting dokumentierte Pflicht zur DB-/Filestore-Verschlüsselung).

## Funktionsumfang der Abnahme

- Angemeldet werden der **Buchungsdatenservice inkl. Belegbild**
  (Modul `datev_connector_documents`: Belegbilder werden VOR dem
  Buchungsstapel per PUT `accounting-documents /clients/{id}/documents/{guid}`
  übertragen; GUID von Odoo erzeugt → keine Dubletten; Metadata mit allen
  drei Ablageebenen category/folder/register; Beleglink Spalte 20
  `BEDI "<guid>"`), der **Belegbilderservice** ist optional pro Firma
  zuschaltbar (eigener Scope datev:accounting:documents), sowie der
  **Lohnaustauschdatenservice (hr:exchange)** für Personalstammdaten.
  Der frühere LODAS-ASCII-Export wurde entfernt; ein späterer
  Bewegungsdaten-Transfer läuft über hr:exchange `month-records`
  (inkl. Storno-Logik: Änderung = negativer Wert + Neuerfassung).
- Produktionsabnahme-Kriterium „Beleg muss in DATEV Rechnungswesen zur
  Buchung angezeigt werden": im Testmandanten mit Musterrechnung + PDF
  vorführen.
