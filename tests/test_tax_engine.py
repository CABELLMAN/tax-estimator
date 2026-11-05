"""Independent IRS schedule examples and financial boundary regressions."""

import csv
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import shutil
import tempfile
import unittest

from tax_engine import DATA_DIR, TaxInputs, estimate_tax, load_rules


class CalculationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_rules()

    def estimate(self, year=2026, status="single", **values):
        return estimate_tax(self.rules[(year, status)], TaxInputs(**values))

    def test_published_irs_base_tax_at_top_bracket_for_every_status_and_year(self):
        # Independent base-tax figures from the IRS revenue procedures in README.
        examples = {
            2024: [(609350, "183647.25"), (731200, "196669.50"),
                   (365600, "98334.75"), (609350, "181954.50"), (731200, "196669.50")],
            2025: [(626350, "188769.75"), (751600, "202154.50"),
                   (375800, "101077.25"), (626350, "187031.50"), (751600, "202154.50")],
            2026: [(640600, "192979.25"), (768700, "206583.50"),
                   (384350, "103291.75"), (640600, "191171.00"), (768700, "206583.50")],
        }
        statuses = ["single", "married_filing_jointly", "married_filing_separately",
                    "head_of_household", "qualifying_surviving_spouse"]
        for year, cases in examples.items():
            for status, (taxable, tax) in zip(statuses, cases):
                with self.subTest(year=year, status=status):
                    result = self.estimate(year, status, income=taxable,
                                           deduction_mode="itemized", itemized_deductions=0)
                    self.assertEqual(result.income_tax, D(tax))

    def test_typical_single_returns(self):
        expected = {2024: "13841.00", 2025: "13449.00", 2026: "13170.00"}
        for year, tax in expected.items():
            with self.subTest(year=year):
                self.assertEqual(self.estimate(year, income=100000).income_tax, D(tax))

    def test_2025_standard_deduction_includes_july_2025_increase(self):
        self.assertEqual(self.rules[(2025, "single")].standard_deduction, D(15750))
        self.assertEqual(self.rules[(2025, "married_filing_jointly")].standard_deduction, D(31500))
        self.assertEqual(self.rules[(2025, "head_of_household")].standard_deduction, D(23625))

    def test_zero_and_fully_deducted_income(self):
        for income in (0, 1, 16100):
            result = self.estimate(income=income)
            self.assertEqual(result.income_tax, 0)
            self.assertEqual(result.taxable_income, 0)
            self.assertEqual(result.effective_rate, 0)

    def test_every_bracket_boundary_has_correct_increment_and_no_jump(self):
        for key, rule in self.rules.items():
            for index, bracket in enumerate(rule.brackets[:-1]):
                with self.subTest(key=key, threshold=bracket.upper):
                    baseline = TaxInputs(income=bracket.upper, deduction_mode="itemized")
                    below = estimate_tax(rule, replace(baseline, income=bracket.upper - 1))
                    at = estimate_tax(rule, baseline)
                    above = estimate_tax(rule, replace(baseline, income=bracket.upper + 1))
                    self.assertEqual(at.income_tax - below.income_tax, bracket.rate)
                    self.assertEqual(above.income_tax - at.income_tax, rule.brackets[index + 1].rate)
                    self.assertEqual(at.next_dollar_bracket_rate, rule.brackets[index + 1].rate)

    def test_open_ended_top_bracket(self):
        result = self.estimate(income=1_000_000, deduction_mode="itemized")
        self.assertEqual(result.income_tax, D("325957.25"))

    def test_deduction_choice(self):
        self.assertEqual(self.estimate(itemized_deductions=20000).deduction_type, "Itemized")
        self.assertEqual(self.estimate(itemized_deductions=10000).deduction_type, "Standard")
        self.assertEqual(self.estimate(deduction_mode="standard", itemized_deductions=40000).deduction_used, D(16100))
        self.assertEqual(self.estimate(deduction_mode="itemized").deduction_used, 0)

    def test_adjustments_and_other_deductions(self):
        result = self.estimate(income=100000, adjustments=10000, other_deductions=5000)
        self.assertEqual(result.adjusted_gross_income, 90000)
        self.assertEqual(result.taxable_income, 68900)
        self.assertEqual(self.estimate(income=100, adjustments=200).taxable_income, 0)

    def test_age_and_blindness_deductions_stack(self):
        result = self.estimate(income=75000, age_65_count=1, blind_count=1)
        self.assertEqual(result.standard_deduction, D(20200))
        self.assertEqual(result.senior_deduction, D(6000))
        self.assertEqual(result.taxable_income, D(48800))

    def test_joint_senior_phaseout_is_per_person(self):
        result = self.estimate(status="married_filing_jointly", income=200000, age_65_count=2)
        self.assertEqual(result.standard_deduction, D(35500))
        self.assertEqual(result.senior_deduction, D(6000))
        self.assertEqual(result.taxable_income, D(158500))
        for income, expected in [(150000, 12000), (250000, 0), (300000, 0)]:
            with self.subTest(income=income):
                result = self.estimate(status="married_filing_jointly", income=income, age_65_count=2)
                self.assertEqual(result.senior_deduction, expected)

    def test_senior_phaseout_magi_and_itemizing(self):
        result = self.estimate(income=75000, age_65_count=1, magi_addbacks=50000,
                               deduction_mode="itemized", itemized_deductions=30000)
        self.assertEqual(result.senior_deduction, D(3000))
        self.assertEqual(result.taxable_income, D(42000))

    def test_senior_deduction_is_zero_in_2024_and_for_separate_returns(self):
        self.assertEqual(self.estimate(2024, income=50000, age_65_count=1).senior_deduction, 0)
        self.assertEqual(self.estimate(status="married_filing_separately", income=50000, age_65_count=1).senior_deduction, 0)

    def test_credits_and_payments_have_distinct_refund_behavior(self):
        result = self.estimate(nonrefundable_credits=20000, refundable_credits=1500,
                               withholding=7000, estimated_payments=2000)
        self.assertEqual(result.income_tax, 0)
        self.assertEqual(result.credits_used, D(13170))
        self.assertEqual(result.balance, D(10500))
        self.assertEqual(self.estimate(withholding=10000).balance, D(-3170))

    def test_blank_optional_values_are_zero(self):
        result = self.estimate(income=None, adjustments="", withholding=None)
        self.assertEqual(result.income_tax, 0)

    def test_invalid_values_are_rejected(self):
        for value in (-1, "bad", "NaN", "Infinity", float("inf"), 1_000_000_000_001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.estimate(income=value)
        for values in ({"age_65_count": 2}, {"blind_count": 0.5}, {"deduction_mode": "invalid"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.estimate(**values)


class CsvRuleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        for source in DATA_DIR.glob("*.csv"):
            shutil.copy(source, self.path / source.name)

    def edit(self, name, transform):
        target = self.path / name
        with target.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            columns, rows = reader.fieldnames, list(reader)
        transform(rows)
        with target.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    def test_adding_a_year_needs_only_csv_rows(self):
        def new_year(rows):
            rows.extend(dict(row, tax_year="2030") for row in list(rows) if row["tax_year"] == "2026")
        self.edit("tax_brackets.csv", new_year)
        self.edit("tax_parameters.csv", new_year)
        rules = load_rules(self.path)
        self.assertEqual(len(rules), 20)
        self.assertEqual(estimate_tax(rules[(2030, "single")], TaxInputs()).income_tax, D("13170.00"))

    def test_csv_changes_control_calculation(self):
        self.edit("tax_parameters.csv", lambda rows: rows[0].update(standard_deduction="99999"))
        result = estimate_tax(load_rules(self.path)[(2024, "single")], TaxInputs(income=99999))
        self.assertEqual(result.income_tax, 0)

    def test_gap_is_rejected(self):
        self.edit("tax_brackets.csv", lambda rows: rows[1].update(lower_bound="11601"))
        with self.assertRaisesRegex(ValueError, "gap, overlap"):
            load_rules(self.path)

    def test_duplicate_parameters_are_rejected(self):
        self.edit("tax_parameters.csv", lambda rows: rows.append(rows[0].copy()))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_rules(self.path)

    def test_missing_final_open_bracket_is_rejected(self):
        self.edit("tax_brackets.csv", lambda rows: rows[6].update(upper_bound="10000000"))
        with self.assertRaisesRegex(ValueError, "last bracket"):
            load_rules(self.path)

    def test_invalid_rate_and_missing_parameter_values_are_rejected(self):
        self.edit("tax_brackets.csv", lambda rows: rows[0].update(rate="10"))
        with self.assertRaisesRegex(ValueError, "decimal rate"):
            load_rules(self.path)

    def test_missing_parameter_row_is_rejected(self):
        self.edit("tax_parameters.csv", lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, "parameter row"):
            load_rules(self.path)


if __name__ == "__main__":
    unittest.main()
