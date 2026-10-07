import unittest
from datetime import datetime, timedelta, timezone

from src.derivative_statistics import estimate_site_derivative_statistics
from src.flow import SiteCapacitySnapshot


def snapshot(at, *, available, charging, zero, location="site-1"):
    effective = available + charging
    return SiteCapacitySnapshot(
        collection_run_id=f"run-{location}-{at.isoformat()}",
        ocpi_location_key=location,
        observation_time_utc=at,
        observed_evse_count=effective,
        offered_evse_count=effective,
        available_evse_count=available,
        charging_evse_count=charging,
        reserved_evse_count=0,
        non_operational_evse_count=0,
        unknown_evse_count=0,
        blocked_evse_count=0,
        unrecognized_status_evse_count=0,
        indeterminate_evse_count=0,
        effective_operational_capacity=effective,
        occupancy_proxy=charging / effective,
        availability_ratio=available / effective,
        zero_availability=zero,
        valid_observation_coverage=1.0,
        minimum_coverage_required=0.8,
    )


class DerivativeStatisticsTest(unittest.TestCase):
    def test_short_history_is_descriptive_but_not_qualified(self):
        start = datetime(2026, 10, 7, tzinfo=timezone.utc)
        rows = [
            snapshot(start + timedelta(hours=hour), available=1, charging=1, zero=False)
            for hour in range(24)
        ]
        result = estimate_site_derivative_statistics(
            rows,
            expected_cadence_seconds=3600,
            bootstrap_repetitions=100,
        )[0]
        self.assertFalse(result.statistically_qualified)
        self.assertAlmostEqual(result.mean_availability_ratio, 0.5)
        self.assertIsNone(result.mean_availability_ratio_ci_lower)
        self.assertIn("history_span_below_7_days", result.qualification_reasons)

    def test_qualified_history_gets_day_block_confidence_intervals(self):
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        rows = []
        for hour in range(8 * 24 + 1):
            at = start + timedelta(hours=hour)
            zero = at.hour in {8, 9, 17}
            rows.append(snapshot(
                at,
                available=0 if zero else 1,
                charging=2 if zero else 1,
                zero=zero,
            ))
        result = estimate_site_derivative_statistics(
            rows,
            expected_cadence_seconds=3600,
            bootstrap_repetitions=200,
        )[0]
        self.assertTrue(result.statistically_qualified)
        self.assertEqual(result.qualification_reasons, ())
        self.assertIsNotNone(result.mean_availability_ratio_ci_lower)
        self.assertIsNotNone(result.zero_availability_snapshot_share_ci_upper)
        self.assertLessEqual(
            result.zero_availability_snapshot_share_ci_lower,
            result.zero_availability_snapshot_share,
        )
        self.assertGreaterEqual(
            result.zero_availability_snapshot_share_ci_upper,
            result.zero_availability_snapshot_share,
        )

    def test_missing_snapshots_fail_expected_coverage(self):
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        rows = [
            snapshot(start + timedelta(days=day), available=1, charging=1, zero=False)
            for day in range(9)
        ]
        result = estimate_site_derivative_statistics(
            rows,
            expected_cadence_seconds=3600,
            bootstrap_repetitions=100,
        )[0]
        self.assertFalse(result.statistically_qualified)
        self.assertTrue(any(
            reason.startswith("eligible_expected_coverage_below")
            for reason in result.qualification_reasons
        ))


if __name__ == "__main__":
    unittest.main()
