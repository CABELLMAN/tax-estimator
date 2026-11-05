"""Run with `python app.py`, then open http://127.0.0.1:8050."""

from __future__ import annotations

import csv
from dataclasses import fields, replace
from io import StringIO

from dash import Dash, Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from tax_engine import TaxInputs, TaxRule, TaxEstimate, estimate_tax, load_rules

RULES = load_rules()
YEARS = sorted({year for year, _ in RULES}, reverse=True)
DEFAULT_YEAR = YEARS[0]
DEFAULT_STATUS = next(status for year, status in RULES if year == DEFAULT_YEAR)
GREEN = "#147d64"
INK = "#203833"
COLORS = ["#d9ede5", "#badfce", "#8ecbb3", "#60b699", "#389b7d", "#147d64", "#0c5748"]
INPUT_IDS = [field.name.replace("_", "-") for field in fields(TaxInputs)]
GRAPH_CONFIG = {"displayModeBar": False, "responsive": True}

app = Dash(__name__, title="Tax Estimator", update_title=None)
server = app.server


def currency(value, cents=False):
    return f"${value:,.2f}" if cents else f"${value:,.0f}"


def field(label, component_id, value=0, hint=None):
    return html.Div([
        html.Label(label, htmlFor=component_id),
        html.Div([html.Span("$", className="currency-prefix"),
                  dcc.Input(id=component_id, type="number", min=0, max=1_000_000_000_000,
                            step="any", value=value, debounce=True, className="money-input")],
                 className="money-field"),
        html.Small(hint, className="field-hint") if hint else None,
    ], className="field")


def count_field(label, component_id):
    return html.Div([html.Label(label, htmlFor=component_id),
                     dcc.Dropdown(id=component_id, options=[0, 1], value=0,
                                  clearable=False, searchable=False)], className="field")


def make_layout():
    initial_options = [{"label": rule.label, "value": rule.status}
                       for rule in RULES.values() if rule.year == DEFAULT_YEAR]
    return html.Div([
        html.Header([
            html.A([html.Span("T", className="brand-mark"), html.Span("Tax Estimator")],
                   href="/", className="brand"),
            html.Div([html.Span(className="status-dot"), "U.S. federal income tax"], className="header-note"),
        ], className="topbar"),
        html.Main([
            html.Div([
                html.Div([html.P("A CLEARER PICTURE", className="eyebrow"),
                          html.H1(["Make sense of ", html.Span("your taxes.")]),
                          html.P("Explore your estimate, see how brackets work, and plan for the year ahead.",
                                 className="intro-copy")]),
                html.Span("2024–2026 rules included" if set(YEARS) == {2024, 2025, 2026}
                          else f"{len(YEARS)} tax years available", className="year-badge"),
            ], className="intro"),
            html.Div([
                html.Aside([
                    html.Div([html.Span("01", className="step-number"), html.H2("Your details")], className="panel-heading"),
                    html.P("All amounts are annual, in U.S. dollars.", className="muted small"),
                    html.Div([
                        html.Label("Tax year", htmlFor="tax-year"),
                        dcc.Dropdown(id="tax-year", options=YEARS, value=DEFAULT_YEAR,
                                     clearable=False, searchable=False),
                    ], className="field"),
                    html.Div([
                        html.Label("Filing status", htmlFor="filing-status"),
                        dcc.Dropdown(id="filing-status", options=initial_options, value=DEFAULT_STATUS,
                                     clearable=False, searchable=False),
                    ], className="field"),
                    field("Annual ordinary income", "income", 100000,
                          "Wages, interest, and other income taxed at ordinary rates, before adjustments."),
                    field("Income adjustments", "adjustments", hint="Eligible pretax contributions and other adjustments. Do not subtract amounts already excluded from income."),
                    html.Hr(),
                    html.H3("Deductions"),
                    dcc.RadioItems(id="deduction-mode", value="auto", className="radio-group", options=[
                        {"label": "Use the larger deduction", "value": "auto"},
                        {"label": "Standard deduction", "value": "standard"},
                        {"label": "Itemized deductions", "value": "itemized"},
                    ]),
                    field("Eligible itemized deductions", "itemized-deductions",
                          hint="Enter the allowed total after any caps or limitations."),
                    html.Details([
                        html.Summary("Age & additional deductions"),
                        html.P("Count eligible people on this return. A person may count in both age and blindness.", className="muted small"),
                        html.Div([count_field("People age 65+", "age-65-count"),
                                  count_field("Blind people", "blind-count")], className="count-grid"),
                        field("Senior deduction MAGI addbacks", "magi-addbacks", hint="Excluded foreign or territory income added back to AGI for the enhanced senior deduction."),
                        field("Other eligible deductions", "other-deductions", hint="Already calculated amounts, such as eligible QBI or Schedule 1-A deductions. Exclude the senior deduction calculated here."),
                    ], className="input-details"),
                    html.Details([
                        html.Summary("Credits & tax payments"),
                        html.P("Enter amounts you qualify for. Eligibility and phaseouts for credits are not calculated.", className="muted small"),
                        field("Nonrefundable tax credits", "nonrefundable-credits"),
                        field("Refundable tax credits", "refundable-credits"),
                        field("Federal income tax withheld", "withholding"),
                        field("Estimated tax payments", "estimated-payments"),
                    ], className="input-details"),
                    html.P("Estimates update when you leave a number field or press Enter.", className="input-footer"),
                ], className="input-panel"),
                html.Section([
                    html.Div(id="input-error", role="alert"),
                    dcc.Loading(html.Div(id="results", **{"aria-live": "polite"}), color=GREEN, delay_show=250),
                    html.Div([
                        html.Button([html.Span("↓ ", className="download-icon"), "Download estimate"],
                                    id="download-button", className="download-button", n_clicks=0),
                        html.Span("CSV report", className="muted small"),
                        dcc.Download(id="download-estimate"),
                        html.Div(id="download-error", role="alert"),
                    ], className="export-row"),
                ], className="results-column"),
            ], className="workspace"),
            html.Footer([
                html.Strong("About this estimate"),
                html.P("Uses progressive federal ordinary income tax rates. Excludes state and local taxes, payroll and self-employment taxes, AMT, NIIT, and preferential rates for capital gains and qualified dividends. Enter only the taxable portion of Social Security or retirement income. This is a planning estimate; IRS tax tables and return rounding may produce different amounts."),
                html.P("Assumes you are eligible for the selected filing status and deductions and cannot be claimed as a dependent. If married filing separately and your spouse itemizes, select itemized deductions. Enhanced senior deductions assume qualifying SSNs and filing eligibility. The displayed bracket rate excludes changes caused by deduction or credit phaseouts."),
            ], className="scope-note"),
        ], className="page"),
    ])


app.layout = make_layout


def prepare_estimate(year, status, values):
    try:
        rule = RULES[(int(year), status)]
    except (KeyError, ValueError, TypeError):
        raise ValueError("Choose a tax year and filing status available in the tax data.") from None
    inputs = TaxInputs(**dict(zip((field.name for field in fields(TaxInputs)), values)))
    return rule, inputs, estimate_tax(rule, inputs)


def style_chart(figure):
    figure.update_layout(
        template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin={"t": 18, "b": 40, "l": 55, "r": 15}, height=280,
        font={"family": "Segoe UI, Arial, sans-serif", "color": INK, "size": 12},
        showlegend=False, hoverlabel={"bgcolor": INK, "font_color": "white"},
    )
    figure.update_yaxes(gridcolor="#edf0eb", zeroline=False, tickprefix="$")
    figure.update_xaxes(showgrid=False, zeroline=False)
    return figure


def bracket_figure(estimate: TaxEstimate):
    figure = go.Figure(go.Bar(
        x=[f"{row.bracket.rate:.0%}" for row in estimate.brackets],
        y=[float(row.tax) for row in estimate.brackets],
        marker={"color": COLORS[:len(estimate.brackets)], "cornerradius": 5},
        customdata=[float(row.taxable_amount) for row in estimate.brackets],
        hovertemplate="%{x} bracket<br>Income in bracket: $%{customdata:,.2f}<br>Tax: $%{y:,.2f}<extra></extra>",
    ))
    style_chart(figure)
    figure.update_layout(bargap=0.4)
    figure.update_xaxes(title="Tax bracket")
    if estimate.tax_before_credits == 0:
        figure.add_annotation(text="No tax before credits at this income", x=0.5, y=0.85,
                              xref="paper", yref="paper", showarrow=False)
    return figure


def income_figure(rule: TaxRule, inputs: TaxInputs, estimate: TaxEstimate):
    end = min(1_000_000_000_000, max(100000, float(estimate.income) * 1.6))
    incomes = sorted({end * index / 80 for index in range(81)} | {float(estimate.income)})
    taxes = [float(estimate_tax(rule, replace(inputs, income=income)).income_tax) for income in incomes]
    figure = go.Figure(go.Scatter(
        x=incomes, y=taxes, mode="lines", line={"color": GREEN, "width": 3},
        fill="tozeroy", fillcolor="rgba(20,125,100,.07)",
        hovertemplate="Income: $%{x:,.0f}<br>Income tax: $%{y:,.2f}<extra></extra>",
    ))
    figure.add_trace(go.Scatter(
        x=[float(estimate.income)], y=[float(estimate.income_tax)], mode="markers",
        marker={"size": 11, "color": GREEN, "line": {"color": "white", "width": 2}},
        hovertemplate="Your estimate<br>Income: $%{x:,.0f}<br>Income tax: $%{y:,.2f}<extra></extra>",
    ))
    style_chart(figure)
    figure.update_xaxes(title="Annual ordinary income", tickprefix="$", nticks=5)
    return figure


def metric(label, value, caption, accent=False):
    return html.Div([html.P(label, className="metric-label"), html.Div(value, className="metric-value"),
                     html.P(caption, className="metric-caption")], className="metric accent" if accent else "metric")


def calculation_row(label, value, total=False):
    return html.Div([html.Span(label), html.Strong(currency(value, True))],
                    className="calculation-row total" if total else "calculation-row")


def render_results(rule: TaxRule, inputs: TaxInputs, estimate: TaxEstimate):
    refund = estimate.balance >= 0
    table_rows = []
    for row in estimate.brackets:
        lower = currency(row.bracket.lower)
        band = f"Over {lower}" if row.bracket.upper is None else (
            f"{lower} – {currency(row.bracket.upper)}" if row.bracket.lower == 0
            else f"Over {lower} – {currency(row.bracket.upper)}")
        table_rows.append(html.Tr([
            html.Td(f"{row.bracket.rate:.0%}"), html.Td(band),
            html.Td(currency(row.taxable_amount, True)), html.Td(currency(row.tax, True)),
        ], className="active-bracket" if row.taxable_amount else "unused-bracket"))
    return [
        html.Div([html.Div([html.Span(className="status-dot"),
                           html.Span(f"{rule.year} ESTIMATE", className="eyebrow")], className="estimate-label"),
                  html.Span(rule.label, className="muted small")], className="result-heading"),
        html.Div([
            metric("Federal income tax", currency(estimate.income_tax, True), "After nonrefundable credits", True),
            metric("Effective tax rate", f"{estimate.effective_rate:.2%}", "Income tax ÷ ordinary income"),
            metric("Taxable income", currency(estimate.taxable_income, True),
                   f"Next-dollar bracket: {estimate.next_dollar_bracket_rate:.0%}"),
            metric("Estimated refund" if refund else "Estimated amount due", currency(abs(estimate.balance), True),
                   "Payments + refundable credits − tax" if refund else "Tax − payments − refundable credits"),
        ], className="metrics-grid"),
        html.Div([
            html.Div([
                html.H2("Your tax, bracket by bracket"),
                html.P("Only the income in each bracket gets that rate.", className="muted small"),
                dcc.Graph(id="bracket-chart", figure=bracket_figure(estimate), config=GRAPH_CONFIG),
            ], className="chart-panel"),
            html.Div([
                html.H2("What if your income changes?"),
                html.P("Same deductions and credits; senior phaseout recalculates.", className="muted small"),
                dcc.Graph(id="income-chart", figure=income_figure(rule, inputs, estimate), config=GRAPH_CONFIG),
            ], className="chart-panel"),
        ], className="charts-grid"),
        html.Div([
            html.Div([
                html.H2("The bracket breakdown"),
                html.P("Brackets apply to taxable income, after deductions.", className="muted small"),
                html.Div(html.Table([
                    html.Thead(html.Tr([html.Th("Rate"), html.Th("Taxable income range"),
                                       html.Th("Your income"), html.Th("Your tax")])),
                    html.Tbody(table_rows),
                    html.Tfoot(html.Tr([html.Td("Tax before credits", colSpan=3),
                                       html.Td(currency(estimate.tax_before_credits, True))])),
                ]), className="table-scroll"),
                html.P("Each range includes its upper limit. Tax is summed before rounding to cents.", className="table-note"),
            ], className="detail-panel bracket-panel"),
            html.Div([
                html.H2("How we got there"),
                calculation_row("Ordinary income", estimate.income),
                calculation_row("Income adjustments", estimate.adjusted_gross_income - estimate.income),
                calculation_row("Adjusted gross income", estimate.adjusted_gross_income, True),
                calculation_row(f"{estimate.deduction_type} deduction", -estimate.deduction_used),
                calculation_row("Enhanced senior deduction", -estimate.senior_deduction),
                calculation_row("Other eligible deductions", -estimate.other_deductions),
                calculation_row("Taxable income (minimum $0)", estimate.taxable_income, True),
                calculation_row("Tax before credits", estimate.tax_before_credits),
                calculation_row("Nonrefundable credits used", -estimate.credits_used),
                calculation_row("Federal income tax", estimate.income_tax, True),
                calculation_row("Withholding + estimated payments", estimate.payments),
                calculation_row("Refundable credits", estimate.refundable_credits),
                html.P(f"Available standard deduction: {currency(estimate.standard_deduction, True)}.", className="table-note"),
            ], className="detail-panel calculation-panel"),
        ], className="details-grid"),
        html.Details([
            html.Summary("Tax data & sources"),
            html.P("Tax years, filing options, brackets, standard deductions, and senior phaseout parameters come from the CSV files in data/. Append a year to both files and restart the app to use it.", className="muted small"),
            html.Div([html.A(f"IRS source {index}", href=source, target="_blank", rel="noopener noreferrer")
                      for index, source in enumerate(rule.sources, 1)], className="source-links"),
        ], className="data-note"),
    ]


@app.callback(
    Output("filing-status", "options"), Output("filing-status", "value"),
    Input("tax-year", "value"), State("filing-status", "value"),
)
def update_statuses(year, current):
    options = [{"label": rule.label, "value": rule.status} for rule in RULES.values() if rule.year == year]
    statuses = [option["value"] for option in options]
    return options, current if current in statuses else statuses[0]


@app.callback(
    Output("age-65-count", "options"), Output("age-65-count", "value"),
    Output("blind-count", "options"), Output("blind-count", "value"),
    Input("tax-year", "value"), Input("filing-status", "value"),
    State("age-65-count", "value"), State("blind-count", "value"),
)
def update_counts(year, status, seniors, blind):
    rule = RULES.get((year, status))
    maximum = rule.max_people if rule else 1
    options = list(range(maximum + 1))
    return options, min(seniors or 0, maximum), options, min(blind or 0, maximum)


@app.callback(Output("results", "children"), Output("input-error", "children"),
              Input("tax-year", "value"), Input("filing-status", "value"),
              *[Input(component_id, "value") for component_id in INPUT_IDS])
def update_estimate(year, status, *values):
    try:
        rule, inputs, estimate = prepare_estimate(year, status, values)
        return render_results(rule, inputs, estimate), ""
    except ValueError as exc:
        return [], html.Div(str(exc), className="error-message")


@app.callback(Output("download-estimate", "data"), Output("download-error", "children"),
              Input("download-button", "n_clicks"), State("tax-year", "value"),
              State("filing-status", "value"),
              *[State(component_id, "value") for component_id in INPUT_IDS], prevent_initial_call=True)
def download_estimate(clicks, year, status, *values):
    if not clicks:
        raise PreventUpdate
    try:
        rule, inputs, estimate = prepare_estimate(year, status, values)
    except ValueError as exc:
        return None, html.Div(str(exc), className="error-message")
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Tax year", rule.year])
    writer.writerow(["Filing status", rule.label])
    writer.writerow([])
    writer.writerow(["Input", "Value"])
    for field in fields(inputs):
        value = getattr(inputs, field.name)
        writer.writerow([field.name, 0 if value is None else value])
    writer.writerow([])
    writer.writerow(["Result", "Value"])
    for field in fields(estimate):
        if field.name != "brackets":
            writer.writerow([field.name, str(getattr(estimate, field.name))])
    writer.writerow([])
    writer.writerow(["Lower bound", "Upper bound (blank = unlimited)", "Rate", "Income in bracket", "Tax (unrounded)"])
    for row in estimate.brackets:
        writer.writerow([row.bracket.lower, row.bracket.upper, row.bracket.rate, row.taxable_amount, row.tax])
    writer.writerow([])
    writer.writerow(["Balance sign", "Positive = refund; negative = amount due"])
    writer.writerow(["Scope", "Federal ordinary income rate-schedule estimate; excludes payroll, state, self-employment, AMT, NIIT, preferential capital gains and qualified dividend rates. Credit eligibility and other deductions must be calculated separately."])
    for source in rule.sources:
        writer.writerow(["IRS source", source])
    return dcc.send_string(output.getvalue(), f"tax-estimate-{rule.year}-{rule.status}.csv"), ""


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=False)
