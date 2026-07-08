{
    "name": "DATEV Cloud Connector",
    "version": "17.0.1.1.0",
    "category": "Accounting/Accounting",
    "summary": "Connect Odoo with DATEV Cloud (OAuth2, base API client)",
    "author": "Aquarius Ventures",
    "website": "https://github.com/aquarius-ventures/odoo-datev-connector",
    "license": "LGPL-3",
    "depends": ["base", "mail", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/datev_token_views.xml",
        "views/datev_api_log_views.xml",
        "views/datev_client_select_wizard_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu.xml",
    ],
    "demo": [
        "demo/datev_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [],
    },
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
    "auto_install": False,
}
