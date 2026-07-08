============================
DATEV Cloud Connector for Odoo
============================

.. |badge1| image:: https://img.shields.io/badge/maturity-Beta-yellow.png
   :target: https://odoo-community.org/page/development-status
   :alt: Beta

.. |badge2| image:: https://img.shields.io/badge/licence-LGPL--3-blue.png
   :target: http://www.gnu.org/licenses/lgpl-3.0-standalone.html
   :alt: License: LGPL-3

.. |badge3| image:: https://img.shields.io/badge/github-aquarius--ventures%2Fodoo--datev--connector-lightgray.png?logo=github
   :target: https://github.com/aquarius-ventures/odoo-datev-connector
   :alt: aquarius-ventures/odoo-datev-connector

|badge1| |badge2| |badge3|

This repository provides modules to connect **Odoo 17** with the **DATEV**
cloud data services for accounting and payroll master data.

Supported DATEV data services (official names):

* **DATEV Buchungsdatenservice** — transfer of posting data (DATEV-Format /
  EXTF) to DATEV Rechnungswesen
* **DATEV Lohnaustauschdatenservice (hr:exchange)** — transfer of employee
  master data to the DATEV payroll systems (LODAS / Lohn und Gehalt)

Modules
-------

`datev_connector <datev_connector/>`_
  Base module: OAuth2/OpenID Connect authentication, DATEV API client,
  technical HTTP log, connection settings.

`datev_connector_accounting <datev_connector_accounting/>`_
  Sync of accounting data via the DATEV-Format (EXTF, v700/13) using the
  DATEV Buchungsdatenservice.

`datev_connector_hr <datev_connector_hr/>`_
  Employee master data (Personalstammdaten) sync via the DATEV
  Lohnaustauschdatenservice (hr:exchange).

`datev_connector_payroll <datev_connector_payroll/>`_
  Salary types, payroll runs and import of DATEV payroll results.

Features
--------

* OAuth2 / OpenID Connect (Authorization Code Flow with PKCE and nonce)
  against the DATEV cloud, per-company connections
* Export Odoo journal entries as DATEV-Format Buchungsstapel (EXTF v700/13,
  CP1252) via the DATEV Buchungsdatenservice
* Employee master data sync (read-before-write workflow, asynchronous jobs
  with result verification) via hr:exchange
* Import of DATEV payroll results
* Technical HTTP log of all DATEV API gateway communication (14+ days)
* Sandbox and production environment switching
* Fully configurable account mapping (Odoo ↔ DATEV Kontonummer) and
  tax mapping (BU-Schlüssel)

Requirements
------------

* Odoo 17.0 Community or Enterprise
* A registered app in the `DATEV Developer Portal <https://developer.datev.de>`_
* The respective DATEV data service (Buchungsdatenservice and/or
  Lohnaustauschdatenservice) must be **ordered and activated** for the DATEV
  client, usually via the tax advisor — see
  `go.datev.de/datenservices-einrichten <http://go.datev.de/datenservices-einrichten>`_

Configuration
-------------

1. Install the base module ``datev_connector``
2. Go to **Settings → DATEV Cloud** and enter your Client ID and Client Secret
3. Select the DATEV data services this company uses (only the scopes for the
   selected services are requested)
4. Click **Connect with DATEV** to complete the OAuth2 flow, then run
   **Mandant prüfen** to verify access to the DATEV client
5. Install ``datev_connector_accounting`` and/or ``datev_connector_hr`` /
   ``datev_connector_payroll`` as needed

.. important::
   **Production redirect URL:** the app registered in the DATEV Developer
   Portal must contain the exact redirect URL
   ``https://<your-domain>/web/datev/oauth/callback``. Production redirect
   URLs must be HTTPS — localhost, IP addresses and custom schemes are not
   allowed and lead to the app being blocked by DATEV (since 2026-03-01).

Bug Tracker
-----------

Bugs are tracked on `GitHub Issues <https://github.com/aquarius-ventures/odoo-datev-connector/issues>`_.
Please contact Aquarius Ventures first-level support for integration issues —
do not contact DATEV or your DATEV member directly for problems with this
integration.

Credits
-------

Authors
~~~~~~~

* `Aquarius Ventures <https://github.com/aquarius-ventures>`_

License
-------

This module is licensed under the `GNU Lesser General Public License v3 or later (LGPLv3+) <http://www.gnu.org/licenses/lgpl-3.0-standalone.html>`_.
