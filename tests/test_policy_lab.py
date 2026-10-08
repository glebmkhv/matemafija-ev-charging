import sqlite3
import unittest
from datetime import datetime, timezone

from src.policy_lab import load_policy_lab_evidence, policy_claims, response_curve


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


if __name__ == "__main__":
    unittest.main()
