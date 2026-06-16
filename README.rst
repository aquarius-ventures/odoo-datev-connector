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

This repository provides modules to connect **Odoo 17** with **DATEV Cloud**
for accounting (Rechnungswesen), payroll (Lohnabrechnung), and HR data
(Personaldaten).

Modules
-------

`datev_connector <datev_connector/>`_
  Base module: OAuth2 authentication, DATEV API client, connection settings.

`datev_connector_accounting <datev_connector_accounting/>`_
  Bidirectional sync of accounting data via DATEV EXTF format.

`datev_connector_payroll <datev_connector_payroll/>`_
  Export payroll and employee data to DATEV LODAS / Lohn und Gehalt.

Features
--------

* OAuth2 / OpenID Connect (Authorization Code Flow) against DATEV Cloud
* Export Odoo journal entries as DATEV EXTF Buchungsstapel
* Export invoices and vendor bills with digital voucher linking
* Import chart of accounts and client metadata from DATEV
* Export employee master data and payroll runs to DATEV LODAS
* Sandbox and production environment switching
* Fully configurable account mapping (Odoo ↔ DATEV Kontonummer)

Requirements
------------

* Odoo 17.0 Community or Enterprise
* A registered app in the `DATEV Developer Portal <https://developer.datev.de>`_
* DATEV Unternehmen Online subscription with API access

Configuration
-------------

1. Install the base module ``datev_connector``
2. Go to **Settings → DATEV Cloud** and enter your Client ID and Client Secret
3. Click **Connect with DATEV** to complete the OAuth2 flow
4. Install ``datev_connector_accounting`` and/or ``datev_connector_payroll``
   as needed

Bug Tracker
-----------

Bugs are tracked on `GitHub Issues <https://github.com/aquarius-ventures/odoo-datev-connector/issues>`_.

Credits
-------

Authors
~~~~~~~

* `Aquarius Ventures <https://github.com/aquarius-ventures>`_

License
-------

This module is licensed under the `GNU Lesser General Public License v3 or later (LGPLv3+) <http://www.gnu.org/licenses/lgpl-3.0-standalone.html>`_.
