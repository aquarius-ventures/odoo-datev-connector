{
    "name": "DATEV Cloud Connector - HR / Personalstammdaten",
    "version": "17.0.1.0.13",
    "category": "Human Resources",
    "summary": "DATEV-Felder auf dem Mitarbeiter: Steuerklasse, SV-Nr., Personalnummer u. a.",
    "author": "Aquarius Ventures",
    "website": "https://github.com/aquarius-ventures/odoo-datev-connector",
    "license": "LGPL-3",
    "depends": ["datev_connector", "hr"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/datev_employee_sync_wizard_views.xml",
        "views/hr_employee_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "datev_connector_hr/static/src/css/datev_employee.css",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
