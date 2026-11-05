# Federal Tax Estimator

A local Python + Plotly Dash app for estimating U.S. federal **ordinary income tax**. Includes tax years **2024, 2025, and 2026** and all five filing statuses.

## Run

Requires Python 3.10 or newer. From this directory:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

Open **http://127.0.0.1:8050**. Stop the server with Ctrl+C. If dependencies are already installed, `python app.py` is sufficient. No database or external service is required; the app listens on localhost and does not persist entries. The development server is intended for local use.

## Features

- Year and filing status selectors populated from CSV data.
- Progressive bracket calculations using `Decimal` for money.
- Automatic choice of the larger standard or eligible itemized deduction, with manual overrides.
- Additional standard deductions for age 65 and blindness.
- Enhanced senior deduction, including the per-person MAGI phaseout for 2025–2026.
- Inputs for eligible income adjustments, other deductions, nonrefundable/refundable credits, withholding, and estimated payments.
- Federal income tax, effective tax rate, taxable income, next-dollar bracket rate, and estimated refund or amount due.
- Interactive Plotly charts, a bracket breakdown, calculation details, and downloadable CSV reports.
- Startup validation for malformed CSV files, missing rules, invalid rates, and bracket gaps or overlaps.

Dollar inputs are annual and update on Enter or when the field loses focus. Blank numeric inputs mean zero. Negative/nonfinite inputs and amounts above $1 trillion are rejected. Age/blindness counts must be whole numbers and cannot exceed the number of eligible people allowed by the selected status.

## Add another tax year

All annual rates and thresholds are in these two files:

| File | One row represents |
| --- | --- |
| `data/tax_brackets.csv` | A tax bracket for one year and filing status |
| `data/tax_parameters.csv` | Deduction and senior phaseout parameters for one year and filing status |

1. Copy the latest year's rows in **both** files and change `tax_year`.
2. Replace every bracket threshold, rate, deduction, and phaseout parameter with the published values for the new year. Do not assume a prior year's rules still apply.
3. Update the IRS source URLs. Set inapplicable numeric parameters to `0`.
4. Run `python -m unittest discover -s tests -v` and restart the app. The new year appears automatically. Existing tests use published values for 2024–2026; add an independent published example for your new year.

Adding a year does not require Python changes when its rules fit the supported calculation model. A legislative change introducing a new kind of calculation requires updating the engine as well as the data.

### Bracket columns

`tax_year,filing_status,lower_bound,upper_bound,rate,source_url`

- `tax_year`: year the income is earned, not the year the return is filed.
- `filing_status`: stable key matching the parameter row.
- `lower_bound`: starts at `0`; each later lower bound equals the previous upper bound. **Do not add $1** to the next lower bound; these are continuous calculation thresholds.
- `upper_bound`: upper taxable-income limit; leave blank only for the final, unlimited bracket.
- `rate`: decimal, e.g. `0.22` for 22%.
- `source_url`: authoritative source for the bracket data.

The taxable amount in a bracket is `max(0, min(taxable_income, upper_bound) - lower_bound)`. Unrounded bracket taxes are summed, then rounded half up to cents. Displayed per-bracket rounded amounts can differ from the rounded total by a cent.

### Parameter columns

| Column | Meaning |
| --- | --- |
| `tax_year`, `filing_status` | Unique pair linking to the bracket rows |
| `label` | Filing status text displayed in the app |
| `standard_deduction` | Base standard deduction |
| `additional_standard_deduction` | Additional amount per age-65 or blindness condition |
| `max_people` | Maximum people eligible for age/blindness counts; `2` for joint returns, otherwise `1` |
| `senior_deduction` | Maximum enhanced senior deduction **per person**; `0` if unavailable |
| `senior_phaseout_start` | MAGI at which the enhanced senior deduction starts phasing out |
| `senior_phaseout_rate` | Decimal reduction rate applied to each person's senior deduction |
| `source_url`, `senior_source_url` | Authoritative deduction sources |

For the enhanced senior deduction, MAGI is AGI plus the entered addbacks. The calculation is `eligible_seniors × max(0, per_person_deduction - phaseout_rate × max(0, MAGI - phaseout_start))`. It applies alongside standard or itemized deductions. The included data disables it for 2024 and married filing separately. The statutory provision currently applies through 2028; **set it to zero when adding later years unless the law changes**.

## Calculation scope

This is a planning tool using federal ordinary income rate schedules, not tax preparation software. It assumes eligibility for the selected filing status and deductions and that the taxpayer cannot be claimed as a dependent. Enter the taxable portion of retirement/Social Security income, not automatically the whole payment. Enter income and adjustments without counting pretax deductions twice.

The app excludes state/local taxes, payroll taxes, self-employment taxes, AMT, NIIT, preferential capital gains/qualified dividend rates, dependent deduction limits, and penalties. It does not calculate credit eligibility, taxable Social Security, QBI, tips/overtime/car-loan deductions, charitable deduction eligibility, or itemized deduction caps/limitations (including the 2026 top-bracket limitation). You may enter already calculated eligible amounts in the relevant deduction/credit fields. Itemized and standard deductions are mutually exclusive; the enhanced senior and other deductions are applied afterward.

If married filing separately and your spouse itemizes, select **Itemized deductions**, even if the result is zero. For an enhanced senior deduction, qualifying SSNs and other filing requirements are assumed. Count a surviving spouse as one person, not two. Special cases involving a deceased spouse on a separate return are outside this estimator's scope.

Nonrefundable credits cannot reduce income tax below zero. Refundable credits are added to payments when computing the refund/amount due. Effective rate is income tax after nonrefundable credits divided by entered ordinary income, before refundable credits. The next-dollar bracket rate is the rate of the next taxable dollar, including at exact thresholds; it does not include the effect of deduction/credit phaseouts. Income sensitivity charts hold all entered amounts constant while recalculating the deduction choice and enhanced senior phaseout at each income.

IRS tax tables for incomes below $100,000 and return-level rounding can produce amounts different from this rate-schedule estimate.

## Sources

Sources are also included in the data, app, and exported reports.

- [2024 brackets and deductions: IRS Revenue Procedure 2023-34](https://www.irs.gov/irb/2023-48_IRB)
- [2025 brackets and additional standard deductions: IRS Revenue Procedure 2024-40](https://www.irs.gov/irb/2024-45_IRB)
- [Revised 2025 standard deductions under the July 2025 legislation](https://www.irs.gov/newsroom/working-families-tax-cuts-individuals-and-workers) — $15,750 single/separate, $31,500 joint/surviving spouse, $23,625 head of household.
- [2026 brackets and deductions: IRS Revenue Procedure 2025-32](https://www.irs.gov/irb/2025-45_IRB)
- [Enhanced senior deduction and phaseout: IRS Schedule 1-A](https://www.irs.gov/pub/irs-pdf/f1040s1a.pdf) and [Form 1040 instructions](https://www.irs.gov/instructions/i1040gi)
- [Dash application reference](https://dash.plotly.com/minimal-app)

## Test

```powershell
python -m unittest discover -s tests -v
```

Tests use Python's standard library and installed app dependencies. They cover published IRS schedule examples for every included year/status, bracket boundaries, deduction selection, senior phaseouts, credits and payments, malformed CSV data, CSV-only year additions, Dash HTTP callbacks, and report exports.

`app.py` contains the Dash UI and callbacks, `assets/style.css` supplies responsive styling, and `tax_engine.py` contains the separately usable calculation engine.
