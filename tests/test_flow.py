import unittest

from src.flow import build_site_capacity_snapshots, build_transition_flow_bins
from src.historical import build_evse_state_intervals


def site_observation(evse, status, *, location="site-1", run="run-1", minute=0):
    return {
        "collection_run_id": run,
        "ocpi_location_key": location,
        "ocpi_evse_key": evse,
        "observed_at": f"2026-10-07T10:{minute:02d}:00+00:00",
        "status_canonical": status,
    }


def state_observation(evse, status, minute):
    return {
        "ocpi_evse_key": evse,
        "observed_at": f"2026-10-07T10:{minute:02d}:00+00:00",
        "status_canonical": status,
    }


class CapacitySnapshotTest(unittest.TestCase):
    def test_separates_demand_capacity_faults_and_unknowns(self):
        snapshots = build_site_capacity_snapshots([
            site_observation("a", "available"),
            site_observation("b", "charging"),
            site_observation("c", "reserved"),
            site_observation("d", "outoforder"),
            site_observation("e", "unknown"),
            site_observation("f", "removed"),
        ], minimum_coverage=0.75)
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertEqual(snapshot.observed_evse_count, 6)
        self.assertEqual(snapshot.offered_evse_count, 5)
        self.assertEqual(snapshot.effective_operational_capacity, 3)
        self.assertEqual(snapshot.non_operational_evse_count, 1)
        self.assertEqual(snapshot.unknown_evse_count, 1)
        self.assertEqual(snapshot.blocked_evse_count, 0)
        self.assertEqual(snapshot.unrecognized_status_evse_count, 0)
        self.assertEqual(snapshot.indeterminate_evse_count, 1)
        self.assertEqual(snapshot.valid_observation_coverage, 0.8)
        self.assertAlmostEqual(snapshot.occupancy_proxy, 1 / 3)
        self.assertAlmostEqual(snapshot.availability_ratio, 1 / 3)
        self.assertFalse(snapshot.zero_availability)

    def test_zero_availability_requires_capacity_and_coverage(self):
        adequate = build_site_capacity_snapshots([
            site_observation("a", "charging"),
            site_observation("b", "reserved"),
        ])[0]
        self.assertTrue(adequate.zero_availability)

        no_capacity = build_site_capacity_snapshots([
            site_observation("a", "outoforder"),
        ])[0]
        self.assertIsNone(no_capacity.zero_availability)

        low_coverage = build_site_capacity_snapshots([
            site_observation("a", "charging"),
            site_observation("b", "unknown"),
        ])[0]
        self.assertIsNone(low_coverage.zero_availability)

    def test_rejects_duplicate_evse_within_snapshot(self):
        with self.assertRaisesRegex(ValueError, "Duplicate EVSE"):
            build_site_capacity_snapshots([
                site_observation("a", "available"),
                site_observation("a", "charging"),
            ])


class TransitionFlowTest(unittest.TestCase):
    def test_bins_transition_upper_bounds_and_includes_empty_bins(self):
        intervals = build_evse_state_intervals([
            state_observation("a", "available", 0),
            state_observation("a", "charging", 5),
            state_observation("a", "charging", 20),
            state_observation("a", "available", 25),
            state_observation("b", "available", 0),
            state_observation("b", "charging", 30),
        ], expected_cadence_seconds=15 * 60)
        bins = build_transition_flow_bins(
            intervals, {"a": "site-1", "b": "site-1"},
            bin_width_minutes=15,
        )
        self.assertEqual(len(bins), 3)
        self.assertEqual(
            [(item.charging_start_proxy_count, item.release_proxy_count) for item in bins],
            [(1, 0), (0, 1), (1, 0)],
        )
        self.assertEqual(bins[0].event_time_assignment, "transition_upper_bound")

    def test_requires_evse_location_mapping(self):
        intervals = build_evse_state_intervals([
            state_observation("a", "available", 0),
        ])
        with self.assertRaisesRegex(ValueError, "Missing location"):
            build_transition_flow_bins(intervals, {})


if __name__ == "__main__":
    unittest.main()
