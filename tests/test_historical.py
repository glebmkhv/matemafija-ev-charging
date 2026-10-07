import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.database_v2 import save_ocpi_locations_snapshot
from src.historical import (
    build_evse_state_intervals,
    load_ocpi_status_observations,
)


def observation(minute, status, evse="evse-1"):
    return {
        "ocpi_evse_key": evse,
        "observed_at": f"2026-10-07T10:{minute:02d}:00+00:00",
        "status_canonical": status,
    }


class StateIntervalTest(unittest.TestCase):
    def test_loads_only_successful_complete_ocpi_snapshots(self):
        location = {
            "country_code": "LT",
            "party_id": "TEST",
            "id": "1",
            "last_updated": "2026-10-07T13:00:00+03:00",
            "evses": [{
                "uid": "1",
                "status": "AVAILABLE",
                "last_updated": "2026-10-07T13:00:00+03:00",
                "connectors": [],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "history.db"
            save_ocpi_locations_snapshot(
                [location], database_path,
                "2026-10-07T10:00:00+00:00", "run-1",
            )
            changed = dict(location)
            changed["evses"] = [dict(location["evses"][0], status="CHARGING")]
            save_ocpi_locations_snapshot(
                [changed], database_path,
                "2026-10-07T10:05:00+00:00", "run-2",
            )
            connection = sqlite3.connect(database_path)
            try:
                observations = load_ocpi_status_observations(connection)
            finally:
                connection.close()

        self.assertEqual(
            [item.status for item in observations],
            ["available", "charging"],
        )
        intervals = build_evse_state_intervals(observations)
        self.assertEqual(len(intervals), 2)

    def test_reconstructs_interval_bounds_and_transition_proxies(self):
        intervals = build_evse_state_intervals([
            observation(0, "available"),
            observation(5, "available"),
            observation(10, "charging"),
            observation(15, "charging"),
            observation(20, "available"),
        ])

        self.assertEqual([item.status for item in intervals], [
            "available", "charging", "available"
        ])
        first, charging, final = intervals
        self.assertTrue(first.left_censored)
        self.assertEqual(first.duration_lower_minutes, 5)
        self.assertIsNone(first.duration_upper_minutes)
        self.assertEqual(charging.interval_start_lower_utc.minute, 5)
        self.assertEqual(charging.interval_start_upper_utc.minute, 10)
        self.assertEqual(charging.interval_end_lower_utc.minute, 15)
        self.assertEqual(charging.interval_end_upper_utc.minute, 20)
        self.assertEqual(charging.duration_lower_minutes, 5)
        self.assertEqual(charging.duration_upper_minutes, 15)
        self.assertEqual(charging.duration_midpoint_minutes, 10)
        self.assertTrue(charging.available_to_charging_transition)
        self.assertEqual(charging.transition_to, "available")
        self.assertTrue(final.charging_to_available_transition)
        self.assertTrue(final.right_censored)

    def test_splits_equal_status_at_large_collection_gap(self):
        intervals = build_evse_state_intervals([
            observation(0, "available"),
            observation(5, "available"),
            observation(30, "available"),
        ])

        self.assertEqual(len(intervals), 2)
        before_gap, after_gap = intervals
        self.assertTrue(before_gap.ends_before_collection_gap)
        self.assertTrue(before_gap.right_censored)
        self.assertTrue(after_gap.starts_after_collection_gap)
        self.assertTrue(after_gap.left_censored)
        self.assertEqual(before_gap.duration_lower_minutes, 5)
        self.assertEqual(after_gap.duration_lower_minutes, 0)

    def test_keeps_evse_series_separate(self):
        intervals = build_evse_state_intervals([
            observation(0, "available", "b"),
            observation(0, "charging", "a"),
            observation(5, "available", "b"),
            observation(5, "charging", "a"),
        ])
        self.assertEqual(
            [(item.ocpi_evse_key, item.status) for item in intervals],
            [("a", "charging"), ("b", "available")],
        )

    def test_rejects_conflicting_statuses_at_same_time(self):
        with self.assertRaisesRegex(ValueError, "Conflicting statuses"):
            build_evse_state_intervals([
                observation(0, "available"),
                observation(0, "charging"),
            ])

    def test_rejects_timezone_naive_observation_time(self):
        with self.assertRaisesRegex(ValueError, "must include a timezone"):
            build_evse_state_intervals([{
                "ocpi_evse_key": "evse-1",
                "observed_at": "2026-10-07T10:00:00",
                "status_canonical": "available",
            }])


if __name__ == "__main__":
    unittest.main()
