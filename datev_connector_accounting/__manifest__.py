{
    "name": "DATEV Cloud Connector - Accounting",
    "version": "17.0.1.2.0",
    "category": "Accounting/Accounting",
    "summary": "Bidirectional sync of journal entries with DATEV Cloud via EXTF format",
    "author": "Aquarius Ventures",
    "website": "https://github.com/aquarius-ventures/odoo-datev-connector",
    "license": "LGPL-3",
    # "account" (Community) statt "account_accountant" (Enterprise): das Modul
    # nutzt nur account.move/account.account/account.tax — Marketplace-Ziel
    # ist Community-Kompatibilität.
    "depends": ["datev_connector", "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/datev_account_mapping_views.xml",
        "views/datev_tax_mapping_views.xml",
        "views/account_move_views.xml",
        "views/datev_export_wizard_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu.xml",
    ],
    "demo": [
        "demo/datev_accounting_demo.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
