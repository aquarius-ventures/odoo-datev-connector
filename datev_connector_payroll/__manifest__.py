{
    "name": "DATEV Cloud Connector - Payroll",
    "version": "17.0.1.0.0",
    "category": "Human Resources/Payroll",
    "summary": "Export payroll and HR data from Odoo to DATEV LODAS / Lohn und Gehalt",
    "author": "Aquarius Ventures",
    "website": "https://github.com/aquarius-ventures/odoo-datev-connector",
    "license": "LGPL-3",
    "depends": ["datev_connector", "hr", "hr_payroll_community"],
    "data": [
        "security/ir.model.access.csv",
        "views/datev_employee_mapping_views.xml",
        "views/datev_payroll_export_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
