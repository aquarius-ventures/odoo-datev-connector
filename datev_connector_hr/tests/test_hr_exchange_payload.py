from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestHrExchangePayload(TransactionCase):
    """Unit tests for hr.employee._build_hr_exchange_payload()."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.de = cls.env.ref("base.de")
        cls.be = cls.env.ref("base.be")

    def _make_emp(self, **vals):
        base = {
            "name": "Maria Schmidt",
            "gender": "female",
            "birthday": date(1990, 5, 1),
            "ssnid": "12345678A12",
            "datev_personnel_number": "42",
            "datev_tax_class": "1",
            "datev_tax_id_number": "12345678901",
            "datev_health_insurance_name": "87880235",
            "datev_health_insurance_type": "gkv",
        }
        base.update(vals)
        return self.env["hr.employee"].sudo().create(base)

    # ── Name & basic identity ────────────────────────────────────────────────
    def test_name_split_and_personnel_number(self):
        payload = self._make_emp()._build_hr_exchange_payload()
        self.assertEqual(payload["surname"], "Schmidt")
        self.assertEqual(payload["first_name"], "Maria")
        # Personnel number is converted to an integer.
        self.assertEqual(payload["personnel_number"], 42)
        self.assertIsInstance(payload["personnel_number"], int)

    def test_single_word_name_has_no_first_name(self):
        payload = self._make_emp(name="Cher")._build_hr_exchange_payload()
        self.assertEqual(payload["surname"], "Cher")
        self.assertNotIn("first_name", payload)

    def test_gender_mapping(self):
        self.assertEqual(
            self._make_emp(gender="male")._build_hr_exchange_payload()["personal_data"]["sex"], "M"
        )
        self.assertEqual(
            self._make_emp(gender="female")._build_hr_exchange_payload()["personal_data"]["sex"], "W"
        )
        self.assertEqual(
            self._make_emp(gender="other")._build_hr_exchange_payload()["personal_data"]["sex"], "D"
        )

    # ── Personnel number validation ──────────────────────────────────────────
    def test_invalid_personnel_number_raises(self):
        for bad in ("0", "abc", "100000", ""):
            with self.assertRaises(UserError):
                self._make_emp(datev_personnel_number=bad)._build_hr_exchange_payload()

    # ── Church tax denomination filter ───────────────────────────────────────
    def test_denomination_valid_passes_through(self):
        payload = self._make_emp(datev_church_tax="ev")._build_hr_exchange_payload()
        self.assertEqual(payload["tax_card"]["denomination"], "ev")

    def test_denomination_ohne_is_filtered(self):
        payload = self._make_emp(datev_church_tax="ohne")._build_hr_exchange_payload()
        self.assertNotIn("denomination", payload.get("tax_card", {}))

    # ── Health insurance contribution class ──────────────────────────────────
    def test_health_insurance_gkv_pkv(self):
        gkv = self._make_emp(datev_health_insurance_type="gkv")._build_hr_exchange_payload()
        pkv = self._make_emp(datev_health_insurance_type="pkv")._build_hr_exchange_payload()
        self.assertEqual(gkv["social_insurance"]["contribution_class_health_insurance"], 1)
        self.assertEqual(pkv["social_insurance"]["contribution_class_health_insurance"], 9)

    # ── Default SI / taxation values (preserve historical behaviour) ─────────
    def test_default_si_and_taxation(self):
        si = self._make_emp()._build_hr_exchange_payload()["social_insurance"]
        self.assertEqual(si["contribution_class_nursing_insurance"], 1)
        self.assertEqual(si["contribution_class_pension_insurance"], 1)
        self.assertEqual(si["contribution_class_unemployment_insurance"], 1)
        tax = self._make_emp()._build_hr_exchange_payload()["taxation"]
        self.assertEqual(tax["employment_type"], 1)
        self.assertEqual(tax["flat_rate_tax"], 0)

    def test_si_overrides_are_int(self):
        emp = self._make_emp(
            datev_si_nursing="2", datev_si_pension="3", datev_si_unemployment="2",
            datev_employment_type="2", datev_flat_rate_tax="2",
        )
        payload = emp._build_hr_exchange_payload()
        si = payload["social_insurance"]
        self.assertEqual(si["contribution_class_nursing_insurance"], 2)
        self.assertEqual(si["contribution_class_pension_insurance"], 3)
        self.assertEqual(si["contribution_class_unemployment_insurance"], 2)
        self.assertEqual(payload["taxation"]["employment_type"], 2)
        self.assertEqual(payload["taxation"]["flat_rate_tax"], 2)

    def test_childless_surcharge_inversion(self):
        # Odoo "Zuschlag berücksichtigen" True → DATEV "...ignored" False, and vice versa.
        on = self._make_emp(datev_si_childless_surcharge=True)._build_hr_exchange_payload()
        off = self._make_emp(datev_si_childless_surcharge=False)._build_hr_exchange_payload()
        self.assertFalse(
            on["social_insurance"]["is_additional_contribution_to_nursing_insurance_for_childless_ignored"]
        )
        self.assertTrue(
            off["social_insurance"]["is_additional_contribution_to_nursing_insurance_for_childless_ignored"]
        )

    # ── country_of_birth mapping ─────────────────────────────────────────────
    def test_country_of_birth_mapped(self):
        de = self._make_emp(country_of_birth=self.de.id)._build_hr_exchange_payload()
        be = self._make_emp(country_of_birth=self.be.id)._build_hr_exchange_payload()
        self.assertEqual(de["personal_data"]["country_of_birth"], "000")
        self.assertEqual(be["personal_data"]["country_of_birth"], "124")

    def test_country_of_birth_absent_when_unset(self):
        payload = self._make_emp()._build_hr_exchange_payload()
        self.assertNotIn("country_of_birth", payload["personal_data"])

    def test_country_of_birth_unmapped_raises(self):
        bogus = self.env["res.country"].sudo().create({"name": "Testland", "code": "QZ"})
        with self.assertRaises(UserError):
            self._make_emp(country_of_birth=bogus.id)._build_hr_exchange_payload()

    # ── Address ──────────────────────────────────────────────────────────────
    def test_address_mapped(self):
        emp = self._make_emp(
            private_street="Roonstr. 101",
            private_zip="90329",
            private_city="Nürnberg",
            private_country_id=self.de.id,
        )
        addr = emp._build_hr_exchange_payload()["address"]
        self.assertEqual(addr["street"], "Roonstr.")
        self.assertEqual(addr["house_number"], "101")
        self.assertEqual(addr["postal_code"], "90329")
        self.assertEqual(addr["city"], "Nürnberg")
        self.assertEqual(addr["country"], "D")

    def test_address_skipped_when_country_unmapped(self):
        emp = self._make_emp(
            private_street="Main St 1",
            private_zip="12345",
            private_country_id=self.env.ref("base.us").id,  # not in _ADDRESS_COUNTRY_MAP
        )
        self.assertNotIn("address", emp._build_hr_exchange_payload())

    def test_address_skipped_when_no_postal_code(self):
        emp = self._make_emp(private_street="Roonstr. 1", private_country_id=self.de.id)
        self.assertNotIn("address", emp._build_hr_exchange_payload())

    def test_split_street_house(self):
        Emp = self.env["hr.employee"]
        self.assertEqual(Emp._split_street_house("Roonstr. 101"), ("Roonstr.", "101"))
        self.assertEqual(Emp._split_street_house("Auf der Schanz 78a"), ("Auf der Schanz", "78a"))
        self.assertEqual(Emp._split_street_house("Hauptstraße"), ("Hauptstraße", None))

    # ── Bank account (IBAN / BIC) ────────────────────────────────────────────
    def test_iban_and_bic(self):
        bank = self.env["res.bank"].create({"name": "Commerzbank", "bic": "COBADEFF760"})
        partner = self.env["res.partner"].create({"name": "EE Bankinhaber"})
        acc = self.env["res.partner.bank"].create({
            "acc_number": "DE94 7604 0061 0524 3712 00",
            "partner_id": partner.id,
            "bank_id": bank.id,
        })
        emp = self._make_emp()
        emp.sudo().write({"bank_account_id": acc.id})
        account = emp._build_hr_exchange_payload()["account"]
        self.assertEqual(account["iban"], "DE94760400610524371200")
        self.assertEqual(account["bic"], "COBADEFF760")

    def test_no_account_when_no_bank(self):
        self.assertNotIn("account", self._make_emp()._build_hr_exchange_payload())

    # ── Employment / compensation variables ──────────────────────────────────
    def test_employment_period_with_termination(self):
        emp = self._make_emp(
            datev_employment_start=date(2020, 3, 1),
            departure_date=date(2024, 12, 31),
        )
        periods = emp._build_hr_exchange_payload()["employment_periods"]
        self.assertEqual(periods[0]["date_of_commencement_of_employment"], "2020-03-01")
        self.assertEqual(periods[0]["date_of_termination_of_employment"], "2024-12-31")

    def test_no_employment_period_without_start(self):
        self.assertNotIn("employment_periods", self._make_emp()._build_hr_exchange_payload())

    def test_activity_fields(self):
        job = self.env["hr.job"].create({"name": "DevOps Engineer"})
        emp = self._make_emp(
            datev_weekly_working_hours=38.5,
            datev_employee_type="106",
            datev_cost_center="KST-1",
            job_id=job.id,
        )
        activity = emp._build_hr_exchange_payload()["activity"]
        self.assertEqual(activity["weekly_working_hours"], 38.5)
        self.assertEqual(activity["employee_type"], "106")
        self.assertEqual(activity["individual_cost_center_id"], "KST-1")
        # Spaces become underscores (DATEV pattern allows only [A-Za-z0-9_]).
        self.assertEqual(activity["occupational_title"], "DevOps_Engineer")

    def test_occupational_title_sanitize(self):
        Emp = self.env["hr.employee"]
        self.assertEqual(Emp._sanitize_occupational_title("Bürokaufmann"), "Buerokaufmann")
        self.assertEqual(Emp._sanitize_occupational_title("Koch & Kellner"), "Koch__Kellner")
        self.assertEqual(Emp._sanitize_occupational_title(""), "")

    def test_payment_method_and_vacation(self):
        emp = self._make_emp(datev_payment_method="5", datev_vacation_days=30.0)
        payload = emp._build_hr_exchange_payload()
        self.assertEqual(payload["payment_method"], "5")
        self.assertEqual(payload["vacation_entitlement"]["basic_vacation_entitlement"], 30.0)

    def test_default_payment_method_present(self):
        # Default datev_payment_method = "1" → always present in payload.
        self.assertEqual(self._make_emp()._build_hr_exchange_payload()["payment_method"], "1")
