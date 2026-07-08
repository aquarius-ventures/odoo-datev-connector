{
    "name": "DATEV Cloud Connector - Belegbilder",
    "version": "17.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "DATEV Belegbilderservice: Belegbilder zu Buchungen nach DATEV Unternehmen online übertragen",
    "author": "Aquarius Ventures",
    "website": "https://github.com/aquarius-ventures/odoo-datev-connector",
    "license": "LGPL-3",
    "depends": ["datev_connector_accounting"],
    "data": [
        "views/account_move_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
