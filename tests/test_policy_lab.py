import sqlite3
import unittest
from datetime import datetime, timezone

from src.policy_lab import (
    illustrative_release_preview, joint_gate_preview,
    load_policy_lab_evidence, policy_claims,
    policy_lab_flow, receiver_choice_curve, response_curve,
)


class PolicyLabTest(unittest.TestCase):
    def test_evidence_summary_screens_history_without_claiming_formal_readiness(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript("""
            CREATE TABLE ocpi_evse_status_observations (observed_at TEXT);
            CREATE TABLE ocpi_locations (
                is_current INTEGER, latitude REAL, longitude REAL
            );
            CREATE TABLE ocpi_tariffs (is_current INTEGER);
            CREATE TABLE ocpi_connector_tariff_assignments (is_current INTEGER);
        """)
        connection.executemany(
            "INSERT INTO ocpi_evse_status_observations VALUES (?)",
            (("2026-10-01T00:00:00+00:00",),
             ("2026-10-09T00:00:00+00:00",)),
        )
        connection.executemany(
            "INSERT INTO ocpi_locations VALUES (?, ?, ?)",
            ((1, 54.68, 25.28), (1, None, None), (0, 54.7, 25.3)),
        )
        connection.execute("INSERT INTO ocpi_tariffs VALUES (1)")
        connection.execute(
            "INSERT INTO ocpi_connector_tariff_assignments VALUES (1)"
        )
        summary = load_policy_lab_evidence(connection)
        self.assertTrue(summary.history_gate_possible)
        self.assertEqual(summary.current_location_count, 2)
        self.assertEqual(summary.coordinate_location_count, 1)

    def test_response_curves_have_expected_identity_and_direction(self):
        intensities = (0, .5, 1)
        release = response_curve(.2, 10, .05, direction="release",
                                 intensity_values=intensities)
        start = response_curve(.2, 10, .05, direction="start",
                               intensity_values=intensities)
        self.assertAlmostEqual(release[0]["probability"], .2)
        self.assertAlmostEqual(start[0]["probability"], .2)
        self.assertGreater(release[-1]["probability"], .2)
        self.assertLess(start[-1]["probability"], .2)

    def test_claims_keep_causal_language_out(self):
        claims = policy_claims()
        self.assertTrue(any("Causal" in item for item in claims["not_supported"]))
        self.assertTrue(any("pilot" in item for item in claims["city_next_action"]))

    def test_credit_and_distance_have_transparent_choice_directions(self):
        low_credit = receiver_choice_curve(
            (0, 10, 25), beta_credit_per_mcu=.1,
            beta_distance_per_km=.5, distance_km=2,
        )
        self.assertLess(
            low_credit[0]["receiver_probability"],
            low_credit[-1]["receiver_probability"],
        )
        near = receiver_choice_curve(
            (10,), beta_credit_per_mcu=.1,
            beta_distance_per_km=.5, distance_km=1,
        )[0]
        far = receiver_choice_curve(
            (10,), beta_credit_per_mcu=.1,
            beta_distance_per_km=.5, distance_km=4,
        )[0]
        self.assertGreater(near["receiver_probability"],
                           far["receiver_probability"])

    def test_policy_lab_flow_covers_evidence_to_decision(self):
        flow = policy_lab_flow()
        self.assertEqual(flow[0][0], "Evidence")
        self.assertEqual(flow[-1][0], "Decision")
        self.assertEqual(len(flow), 6)

    def test_joint_gate_preview_never_promotes_missing_or_failure(self):
        self.assertEqual(
            joint_gate_preview(True, True, True, True), "success",
        )
        self.assertEqual(
            joint_gate_preview(True, None, True, True), "not_evaluable",
        )
        self.assertEqual(
            joint_gate_preview(True, None, False, True), "failure",
        )

    def test_illustrative_preview_is_explicitly_assumed_and_identity_at_zero(self):
        rows = illustrative_release_preview(
            intensity_values=(0, 1), sensitivity_values=(0, 10),
        )
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["provenance"] == "assumed" for row in rows))
        self.assertTrue(all(
            row["claim_scope"] == "illustrative_mechanism_only" for row in rows
        ))
        zero_intensity = [row for row in rows if row["lambda"] == 0]
        self.assertTrue(all(
            abs(row["release_probability_change_pp"]) < 1e-12
            for row in zero_intensity
        ))
        self.assertGreater(rows[-1]["release_probability_change_pp"], 0)


if __name__ == "__main__":
    unittest.main()
