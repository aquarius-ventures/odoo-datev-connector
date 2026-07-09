import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    datev_extf_festschreibung = fields.Boolean(
        string="DATEV Festschreibung",
        default=True,
        help="Header field 21 of exported EXTF files. Enabled (default) means "
        "postings are fixated on import — the GoBD-compliant setting. "
        "Only disable this in coordination with the tax advisor.",
    )
    datev_chart_of_accounts = fields.Selection(
        [("03", "SKR03"), ("04", "SKR04")],
        string="DATEV Sachkontenrahmen",
        help="G/L chart of accounts used in DATEV (EXTF header field 27).",
    )

    # ------------------------------------------------------------------
    # Demo data (called via <function> from demo/datev_accounting_demo.xml)
    # ------------------------------------------------------------------

    @api.model
    def _datev_load_accounting_demo(self):
        """Posted demo invoices for the DATEV sandbox company 455148-1.

        Builds the full accounting demo chain: chart of accounts, demo
        accounts with SKR03 codes, 19%/7% taxes with proper tax accounts,
        BU-Schlüssel and account mappings, and six posted documents covering
        the file-review use cases (AR 19%, AR 7%, AR mixed, credit note,
        two vendor bills). Idempotent — reruns on module update are no-ops.
        """
        company = self.env.ref("datev_connector.company_datev_sandbox_1", raise_if_not_found=False)
        if not company:
            return
        eur = self.env.ref("base.EUR")
        Move = self.env["account.move"].sudo().with_company(company)
        demo_domain = [("company_id", "=", company.id), ("ref", "=like", "DEMO-DATEV-%")]
        existing = Move.search(demo_domain)
        if existing and company.currency_id == eur:
            return
        if existing:
            # Self-heal: an earlier loader version installed generic_coa,
            # which flipped the demo company to USD — recreate in EUR.
            _logger.info(
                "DATEV demo: recreating %d demo documents (company was %s, not EUR).",
                len(existing),
                company.currency_id.name,
            )
            self.env["ir.attachment"].sudo().search(
                [
                    ("res_model", "=", "account.move"),
                    ("res_id", "in", existing.ids),
                ]
            ).unlink()
            existing.button_draft()
            existing.with_context(force_delete=True).unlink()

        # l10n_de is a hard module dependency, so the real German SKR03
        # template (natively EUR) is always available. Never switch an
        # already-loaded chart (template switching can be blocked); the EUR
        # enforcement below covers companies that got generic_coa earlier.
        if not company.chart_template:
            self.env["account.chart.template"].try_loading("de_skr03", company, install_demo=False)
        # Safety net for pre-existing generic_coa demo companies: loading that
        # template flipped the company to USD — the DATEV demo must be EUR.
        if company.currency_id != eur:
            try:
                company.currency_id = eur
            except Exception:
                _logger.warning(
                    "DATEV demo: could not switch company %s back to EUR "
                    "(posted non-demo entries exist?). Demo skipped.",
                    company.name,
                )
                return
        company.write(
            {
                "datev_service_accounting": True,
                "datev_chart_of_accounts": "03",
            }
        )

        Account = self.env["account.account"].sudo().with_company(company)

        def get_or_create_account(code, name, account_type):
            account = Account.search([("code", "=", code), ("company_id", "=", company.id)], limit=1)
            if not account:
                account = Account.create(
                    {
                        "code": code,
                        "name": name,
                        "account_type": account_type,
                        "company_id": company.id,
                    }
                )
            return account

        # SKR03 codes directly on the demo accounts — the EXTF generator falls
        # back to the numeric account code when no mapping exists.
        acc_rev19 = get_or_create_account("8400", "Erlöse 19 % USt (Demo)", "income")
        acc_rev7 = get_or_create_account("8300", "Erlöse 7 % USt (Demo)", "income")
        acc_exp19 = get_or_create_account("3400", "Wareneingang 19 % Vorsteuer (Demo)", "expense")
        acc_ust19 = get_or_create_account("1776", "Umsatzsteuer 19 % (Demo)", "liability_current")
        acc_ust7 = get_or_create_account("1771", "Umsatzsteuer 7 % (Demo)", "liability_current")
        acc_vst19 = get_or_create_account("1576", "Abziehbare Vorsteuer 19 % (Demo)", "asset_current")

        Tax = self.env["account.tax"].sudo()

        def get_or_create_tax(name, amount, type_tax_use, tax_account):
            tax = Tax.search([("name", "=", name), ("company_id", "=", company.id)], limit=1)
            if tax:
                return tax
            repartition = [
                (0, 0, {"repartition_type": "base"}),
                (0, 0, {"repartition_type": "tax", "account_id": tax_account.id}),
            ]
            return Tax.create(
                {
                    "name": name,
                    "amount": amount,
                    "amount_type": "percent",
                    "type_tax_use": type_tax_use,
                    "company_id": company.id,
                    "invoice_repartition_line_ids": repartition,
                    "refund_repartition_line_ids": [
                        (0, 0, {"repartition_type": "base"}),
                        (0, 0, {"repartition_type": "tax", "account_id": tax_account.id}),
                    ],
                }
            )

        tax_s19 = get_or_create_tax("USt 19 % (Demo)", 19.0, "sale", acc_ust19)
        tax_s7 = get_or_create_tax("USt 7 % (Demo)", 7.0, "sale", acc_ust7)
        tax_p19 = get_or_create_tax("Vorsteuer 19 % (Demo)", 19.0, "purchase", acc_vst19)

        # BU-Schlüssel: 3 = 19% USt, 2 = 7% USt, 9 = 19% Vorsteuer
        TaxMapping = self.env["datev.tax.mapping"].sudo()
        for tax, bu_key in ((tax_s19, "3"), (tax_s7, "2"), (tax_p19, "9")):
            if not TaxMapping.search_count([("tax_id", "=", tax.id), ("company_id", "=", company.id)]):
                TaxMapping.create(
                    {
                        "company_id": company.id,
                        "tax_id": tax.id,
                        "datev_bu_key": bu_key,
                    }
                )

        Partner = self.env["res.partner"].sudo()

        def get_or_create_partner(name, city):
            partner = Partner.search([("name", "=", name)], limit=1)
            if not partner:
                partner = Partner.create(
                    {
                        "name": name,
                        "city": city,
                        "country_id": self.env.ref("base.de").id,
                        "is_company": True,
                    }
                )
            return partner

        customer = get_or_create_partner("Demo Kunde GmbH", "Nürnberg")
        vendor = get_or_create_partner("Demo Lieferant AG", "Fürth")

        # Map the generic receivable/payable accounts to DATEV collective
        # accounts — demonstrates datev.account.mapping.
        AccountMapping = self.env["datev.account.mapping"].sudo()
        mapping_targets = (
            (customer.with_company(company).property_account_receivable_id, "1400"),
            (vendor.with_company(company).property_account_payable_id, "1600"),
        )
        for account, datev_number in mapping_targets:
            if account and not AccountMapping.search_count(
                [("account_id", "=", account.id), ("company_id", "=", company.id)]
            ):
                AccountMapping.create(
                    {
                        "company_id": company.id,
                        "account_id": account.id,
                        "datev_account_number": datev_number,
                    }
                )

        # Six posted documents covering the DATEV file-review use cases.
        demo_date = fields.Date.today().replace(day=min(fields.Date.today().day, 28))
        documents = [
            ("out_invoice", customer, "DEMO-DATEV-AR-001", [("Beratungsleistung Juli", 1500.0, acc_rev19, tax_s19)]),
            ("out_invoice", customer, "DEMO-DATEV-AR-002", [("Fachbuch DATEV-Schnittstellen", 89.0, acc_rev7, tax_s7)]),
            (
                "out_invoice",
                customer,
                "DEMO-DATEV-AR-003",
                [("Workshop Buchhaltung", 500.0, acc_rev19, tax_s19), ("Begleitliteratur", 45.0, acc_rev7, tax_s7)],
            ),
            ("out_refund", customer, "DEMO-DATEV-GS-001", [("Gutschrift Beratung", 250.0, acc_rev19, tax_s19)]),
            ("in_invoice", vendor, "DEMO-DATEV-ER-001", [("Wareneinkauf Hardware", 800.0, acc_exp19, tax_p19)]),
            ("in_invoice", vendor, "DEMO-DATEV-ER-002", [("Büromaterial", 120.0, acc_exp19, tax_p19)]),
        ]
        for move_type, partner, ref, lines in documents:
            move = Move.create(
                {
                    "move_type": move_type,
                    "partner_id": partner.id,
                    "company_id": company.id,
                    "invoice_date": demo_date,
                    "date": demo_date,
                    "ref": ref,
                    "invoice_line_ids": [
                        (
                            0,
                            0,
                            {
                                "name": name,
                                "quantity": 1,
                                "price_unit": price,
                                "account_id": account.id,
                                "tax_ids": [(6, 0, [tax.id])],
                            },
                        )
                        for name, price, account, tax in lines
                    ],
                }
            )
            move.action_post()

        # Foreign-currency demo document — intentionally left in DRAFT so the
        # standard export flow is not blocked. Posting and exporting it shows
        # the clean rejection (non-EUR moves are refused with a UserError).
        usd = self.env.ref("base.USD")
        usd.sudo().active = True
        Move.create(
            {
                "move_type": "out_invoice",
                "partner_id": customer.id,
                "company_id": company.id,
                "currency_id": usd.id,
                "invoice_date": demo_date,
                "date": demo_date,
                "ref": "DEMO-DATEV-FW-001",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Fremdwährungs-Testfall (USD) — bewusst Entwurf",
                            "quantity": 1,
                            "price_unit": 100.0,
                            "account_id": acc_rev19.id,
                            "tax_ids": [(6, 0, [tax_s19.id])],
                        },
                    ),
                ],
            }
        )
        _logger.info(
            "DATEV demo: %d posted demo documents (+1 draft FX case) created for %s.",
            len(documents),
            company.name,
        )
