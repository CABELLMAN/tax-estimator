"""CSV-driven U.S. federal ordinary income tax estimates.

No annual thresholds or rates live in this module. Money uses Decimal; each
bracket's tax is retained at full precision until the total is rounded to cents.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

ZERO = Decimal("0")
CENT = Decimal("0.01")
DATA_DIR = Path(__file__).resolve().parent / "data"


def amount(value: object, label: str = "Amount") -> Decimal:
    """Normalize a nonnegative finite number. Blank optional inputs mean zero."""
    try:
        result = Decimal(str(value if value is not None and value != "" else 0))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} must be a number.") from None
    if not result.is_finite() or result < 0:
        raise ValueError(f"{label} must be a finite, nonnegative number.")
    if result > Decimal("1000000000000"):
        raise ValueError(f"{label} must be $1 trillion or less.")
    return result


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TaxBracket:
    lower: Decimal
    upper: Decimal | None
    rate: Decimal


@dataclass(frozen=True)
class TaxRule:
    year: int
    status: str
    label: str
    standard_deduction: Decimal
    additional_standard_deduction: Decimal
    max_people: int
    senior_deduction: Decimal
    senior_phaseout_start: Decimal
    senior_phaseout_rate: Decimal
    brackets: tuple[TaxBracket, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class TaxInputs:
    income: object = 100000
    adjustments: object = 0
    deduction_mode: str = "auto"
    itemized_deductions: object = 0
    age_65_count: object = 0
    blind_count: object = 0
    magi_addbacks: object = 0
    other_deductions: object = 0
    nonrefundable_credits: object = 0
    refundable_credits: object = 0
    withholding: object = 0
    estimated_payments: object = 0


@dataclass(frozen=True)
class BracketResult:
    bracket: TaxBracket
    taxable_amount: Decimal
    tax: Decimal


@dataclass(frozen=True)
class TaxEstimate:
    income: Decimal
    adjusted_gross_income: Decimal
    standard_deduction: Decimal
    deduction_used: Decimal
    deduction_type: str
    senior_deduction: Decimal
    other_deductions: Decimal
    taxable_income: Decimal
    tax_before_credits: Decimal
    credits_used: Decimal
    income_tax: Decimal
    refundable_credits: Decimal
    payments: Decimal
    balance: Decimal  # Positive is a refund; negative is an amount due.
    effective_rate: Decimal
    next_dollar_bracket_rate: Decimal
    brackets: tuple[BracketResult, ...]


def _read_csv(path: Path, columns: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = columns - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: missing columns: {', '.join(sorted(missing))}")
        rows = []
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path.name}:{line}: incorrect number of CSV fields.")
            rows.append({key: value.strip() for key, value in row.items()})
        if not rows:
            raise ValueError(f"{path.name} must contain at least one data row.")
        return rows


def load_rules(data_dir: Path | str = DATA_DIR) -> dict[tuple[int, str], TaxRule]:
    """Validate and load every year/status, including newly appended CSV rows."""
    data_dir = Path(data_dir)
    bracket_rows = _read_csv(data_dir / "tax_brackets.csv", {
        "tax_year", "filing_status", "lower_bound", "upper_bound", "rate", "source_url",
    })
    parameter_rows = _read_csv(data_dir / "tax_parameters.csv", {
        "tax_year", "filing_status", "label", "standard_deduction",
        "additional_standard_deduction", "max_people", "senior_deduction",
        "senior_phaseout_start", "senior_phaseout_rate", "source_url", "senior_source_url",
    })
    grouped: dict[tuple[int, str], list[TaxBracket]] = {}
    sources: dict[tuple[int, str], set[str]] = {}
    for line, row in enumerate(bracket_rows, 2):
        context = f"tax_brackets.csv:{line}"
        try:
            key = (int(row["tax_year"]), row["filing_status"])
            lower = amount(row["lower_bound"], "Lower bound")
            upper = amount(row["upper_bound"], "Upper bound") if row["upper_bound"] else None
            rate = amount(row["rate"], "Rate")
            if not row["lower_bound"] or not row["rate"] or not 0 <= rate <= 1:
                raise ValueError("Lower bound and decimal rate (0 to 1) are required.")
            if upper is not None and upper <= lower:
                raise ValueError("Upper bound must exceed lower bound.")
            grouped.setdefault(key, []).append(TaxBracket(lower, upper, rate))
            sources.setdefault(key, set()).add(row["source_url"])
        except ValueError as exc:
            raise ValueError(f"{context}: {exc}") from exc

    rules = {}
    numeric_fields = (
        "standard_deduction", "additional_standard_deduction", "senior_deduction",
        "senior_phaseout_start", "senior_phaseout_rate",
    )
    for line, row in enumerate(parameter_rows, 2):
        context = f"tax_parameters.csv:{line}"
        try:
            key = (int(row["tax_year"]), row["filing_status"])
            if key in rules:
                raise ValueError(f"Duplicate year/status: {key}.")
            if key[0] < 1900 or not key[1] or not row["label"]:
                raise ValueError("A valid year, filing status and label are required.")
            if any(not row[field] for field in (*numeric_fields, "max_people")):
                raise ValueError("All numeric parameters are required; use 0 when inapplicable.")
            values = {field: amount(row[field], field.replace("_", " ")) for field in numeric_fields}
            max_people = int(row["max_people"])
            if max_people not in (1, 2) or values["senior_phaseout_rate"] > 1:
                raise ValueError("max_people must be 1 or 2 and phaseout rate must be 0 to 1.")
            brackets = sorted(grouped.get(key, []), key=lambda bracket: bracket.lower)
            if not brackets or brackets[0].lower != 0:
                raise ValueError(f"Brackets for {key} must start at zero.")
            for previous, current in zip(brackets, brackets[1:]):
                if previous.upper != current.lower:
                    raise ValueError(f"Brackets for {key} have a gap, overlap, or premature open end.")
            if brackets[-1].upper is not None:
                raise ValueError(f"The last bracket for {key} must have a blank upper_bound.")
            links = sources[key] | {row["source_url"], row["senior_source_url"]}
            rules[key] = TaxRule(*key, row["label"], max_people=max_people,
                                 brackets=tuple(brackets), sources=tuple(sorted(links - {""})), **values)
        except ValueError as exc:
            raise ValueError(f"{context}: {exc}") from exc
    if set(grouped) != set(rules):
        raise ValueError("Each year/status in tax_brackets.csv needs exactly one parameter row.")
    return rules


def estimate_tax(rule: TaxRule, inputs: TaxInputs) -> TaxEstimate:
    """Compute a progressive rate-schedule estimate, not an IRS tax-table return."""
    income = amount(inputs.income, "Ordinary income")
    adjustments = amount(inputs.adjustments, "Income adjustments")
    itemized = amount(inputs.itemized_deductions, "Itemized deductions")
    addbacks = amount(inputs.magi_addbacks, "MAGI addbacks")
    other_deductions = amount(inputs.other_deductions, "Other eligible deductions")
    nonrefundable = amount(inputs.nonrefundable_credits, "Nonrefundable credits")
    refundable = amount(inputs.refundable_credits, "Refundable credits")
    withholding = amount(inputs.withholding, "Federal withholding")
    estimated_payments = amount(inputs.estimated_payments, "Estimated payments")
    counts = []
    for value, label in ((inputs.age_65_count, "People age 65+"), (inputs.blind_count, "Blind people")):
        count = amount(value, label)
        if count != count.to_integral_value() or count > rule.max_people:
            raise ValueError(f"{label} must be a whole number from 0 to {rule.max_people} for this filing status.")
        counts.append(int(count))
    seniors, blind = counts
    agi = max(ZERO, income - adjustments)
    standard = rule.standard_deduction + (seniors + blind) * rule.additional_standard_deduction
    if inputs.deduction_mode not in ("auto", "standard", "itemized"):
        raise ValueError("Choose automatic, standard, or itemized deductions.")
    use_itemized = inputs.deduction_mode == "itemized" or (
        inputs.deduction_mode == "auto" and itemized > standard
    )
    deduction = itemized if use_itemized else standard
    # The phaseout reduces the per-person amount, then multiplies by people.
    senior_per_person = max(ZERO, rule.senior_deduction - rule.senior_phaseout_rate *
                            max(ZERO, agi + addbacks - rule.senior_phaseout_start))
    senior = money(senior_per_person * seniors)
    taxable = max(ZERO, agi - deduction - senior - other_deductions)
    breakdown = tuple(
        BracketResult(bracket, portion, portion * bracket.rate)
        for bracket in rule.brackets
        for portion in [max(ZERO, min(taxable, bracket.upper if bracket.upper is not None else taxable) - bracket.lower)]
    )
    before_credits = money(sum((row.tax for row in breakdown), ZERO))
    credits_used = min(before_credits, money(nonrefundable))
    income_tax = before_credits - credits_used
    payments = money(withholding + estimated_payments)
    next_rate = next(bracket.rate for bracket in rule.brackets
                     if bracket.upper is None or taxable < bracket.upper)
    return TaxEstimate(
        income=income, adjusted_gross_income=agi, standard_deduction=standard,
        deduction_used=deduction, deduction_type="Itemized" if use_itemized else "Standard",
        senior_deduction=senior, other_deductions=other_deductions, taxable_income=taxable,
        tax_before_credits=before_credits, credits_used=credits_used, income_tax=income_tax,
        refundable_credits=money(refundable), payments=payments,
        balance=money(payments + refundable - income_tax),
        effective_rate=income_tax / income if income else ZERO,
        next_dollar_bracket_rate=next_rate, brackets=breakdown,
    )
