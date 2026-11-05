"""Exercise the real Dash JSON callback endpoints without browser dependencies."""

import csv
from dataclasses import fields
from io import StringIO
import json
import unittest

import app
from tax_engine import TaxInputs


class DashIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = app.server.test_client()

    def callback(self, output_id, values=None, download=False):
        key = next(key for key in app.app.callback_map if output_id in key)
        metadata = app.app.callback_map[key]
        inputs = [{"id": "tax-year", "property": "value", "value": 2026},
                  {"id": "filing-status", "property": "value", "value": "single"}]
        inputs.extend({"id": field.name.replace("_", "-"), "property": "value",
                       "value": getattr(values or TaxInputs(), field.name)} for field in fields(TaxInputs))
        outputs = [{"id": output.component_id, "property": output.component_property}
                   for output in metadata["output"]]
        return self.client.post("/_dash-update-component", json={
            "output": key, "outputs": outputs,
            "inputs": [{"id": "download-button", "property": "n_clicks", "value": 1}] if download else inputs,
            "state": inputs if download else [],
            "changedPropIds": ["download-button.n_clicks" if download else "income.value"],
        })

    def test_page_layout_callbacks_and_styles_are_served(self):
        for url in ("/", "/_dash-layout", "/_dash-dependencies", "/assets/style.css"):
            with self.subTest(url=url):
                with self.client.get(url) as response:
                    self.assertEqual(response.status_code, 200)

    def test_real_estimate_callback_returns_updated_metrics_and_plotly_figures(self):
        response = self.callback("results.children")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["response"]
        self.assertEqual(data["input-error"]["children"], "")
        serialized = json.dumps(data["results"])
        self.assertIn("$13,170.00", serialized)
        self.assertIn("bracket-chart", serialized)
        self.assertIn("income-chart", serialized)

    def test_invalid_input_clears_results(self):
        response = self.callback("results.children", TaxInputs(income=-1))
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["response"]
        self.assertEqual(data["results"]["children"], [])
        self.assertIn("nonnegative", json.dumps(data["input-error"]))

    def test_sensitivity_chart_accepts_maximum_supported_income(self):
        response = self.callback("results.children", TaxInputs(income=1_000_000_000_000))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["response"]["input-error"]["children"], "")

    def test_download_contains_report_inputs_results_and_brackets(self):
        response = self.callback("download-estimate.data", TaxInputs(withholding=15000), download=True)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["response"]["download-estimate"]["data"]
        self.assertEqual(data["filename"], "tax-estimate-2026-single.csv")
        rows = list(csv.reader(StringIO(data["content"])))
        self.assertIn(["income_tax", "13170.00"], rows)
        self.assertIn(["balance", "1830.00"], rows)
        self.assertIn(["withholding", "15000"], rows)
        self.assertTrue(any(row and row[0] == "Lower bound" for row in rows))

    def test_invalid_download_does_not_generate_a_file(self):
        response = self.callback("download-estimate.data", TaxInputs(income=-1), download=True)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["response"]
        self.assertIsNone(data["download-estimate"]["data"])
        self.assertIn("nonnegative", json.dumps(data["download-error"]))

    def test_switching_status_clamps_counts_to_allowed_people(self):
        self.assertEqual(app.update_counts(2026, "single", 2, 2), ([0, 1], 1, [0, 1], 1))
        self.assertEqual(app.update_counts(2026, "married_filing_jointly", 2, 2), ([0, 1, 2], 2, [0, 1, 2], 2))


if __name__ == "__main__":
    unittest.main()
