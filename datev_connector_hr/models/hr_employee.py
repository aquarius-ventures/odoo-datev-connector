from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # ── Allgemein ───────────────────────────────────────────────────────────
    datev_personnel_number = fields.Char(
        string="Personalnummer (DATEV)",
        groups="hr.group_hr_user",
        help="Eindeutige Personalnummer in DATEV LODAS / Lohn und Gehalt.",
    )
    datev_cost_center = fields.Char(
        string="Kostenstelle",
        groups="hr.group_hr_user",
    )

    # ── Steuer ──────────────────────────────────────────────────────────────
    datev_tax_class = fields.Selection(
        [("1", "I"), ("2", "II"), ("3", "III"), ("4", "IV"), ("5", "V"), ("6", "VI")],
        string="Steuerklasse",
        groups="hr.group_hr_user",
    )
    datev_tax_id_number = fields.Char(
        string="Steueridentifikationsnummer",
        groups="hr.group_hr_user",
        help="11-stellige persönliche Steuer-ID (nicht die USt-IdNr.).",
    )
    datev_church_tax = fields.Selection(
        [
            ("ohne", "Keine Kirchensteuer"),
            ("ev", "Evangelisch (ev)"),
            ("rk", "Römisch-Katholisch (rk)"),
            ("lt", "Lutherisch (lt)"),
            ("ak", "Alt-Katholisch (ak)"),
            ("is", "Islamisch (is)"),
            ("jd", "Jüdisch (jd)"),
            ("andere", "Andere"),
        ],
        string="Konfession / Kirchensteuer",
        groups="hr.group_hr_user",
    )

    # ── Sozialversicherung ──────────────────────────────────────────────────
    datev_health_insurance_name = fields.Char(
        string="Krankenkasse",
        groups="hr.group_hr_user",
    )
    datev_health_insurance_type = fields.Selection(
        [("gkv", "GKV – Gesetzlich"), ("pkv", "PKV – Privat")],
        string="Versicherungsart",
        groups="hr.group_hr_user",
    )
    datev_child_allowance = fields.Float(
        string="Kinderfreibetrag",
        digits=(4, 1),
        groups="hr.group_hr_user",
        help="z. B. 0.5 je Kind bei gemeinsamer Veranlagung.",
    )
