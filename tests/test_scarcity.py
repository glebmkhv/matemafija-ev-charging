import unittest
from datetime import datetime, timezone

from src.flow import SiteCapacitySnapshot
from src.scarcity import (
    build_scarcity_snapshot_metrics,
    build_zero_availability_episodes,
    summarize_site_scarcity,
)


def snapshot(minute, *, available, charging=0, reserved=0,
             non_operational=0, indeterminate=0, zero=None, location="site-1"):
    effective = available + charging + reserved
    offered = effective + non_operational + indeterminate
    coverage = (offered - indeterminate) / offered if offered else None
    return SiteCapacitySnapshot(
        collection_run_id=f"run-{location}-{minute}",
        ocpi_location_key=location,
        observation_time_utc=datetime(2026, 10, 7, 10, minute, tzinfo=timezone.utc),
        observed_evse_count=offered,
        offered_evse_count=offered,
        available_evse_count=available,
        charging_evse_count=charging,
        reserved_evse_count=reserved,
        non_operational_evse_count=non_operational,
        unknown_evse_count=indeterminate,
        blocked_evse_count=0,
        unrecognized_status_evse_count=0,
        indeterminate_evse_count=indeterminate,
        effective_operational_capacity=effective,
        occupancy_proxy=charging / effective if effective else None,
        availability_ratio=available / effective if effective else None,
        zero_availability=zero,
        valid_observation_coverage=coverage,
        minimum_coverage_required=0.8,
    )


class ScarcityMetricTest(unittest.TestCase):
    def test_separates_operational_scarcity_from_equipment_loss(self):
        metrics = build_scarcity_snapshot_metrics([
            snapshot(0, available=1, charging=2, non_operational=1, zero=False),
        ])
        metric = metrics[0]
        self.assertAlmostEqual(metric.operational_scarcity_ratio, 2 / 3)
        self.assertAlmostEqual(metric.equipment_unavailability_ratio, 1 / 4)
        self.assertTrue(metric.evidence_eligible)
        self.assertFalse(metric.zero_availability_evidence)

    def test_builds_interval_censored_zero_availability_episode(self):
        rows = [
            snapshot(0, available=1, charging=1, zero=False),
            snapshot(5, available=0, charging=2, zero=True),
            snapshot(10, available=0, charging=2, zero=True),
            snapshot(15, available=1, charging=1, zero=False),
        ]
        episode = build_zero_availability_episodes(rows)[0]
        self.assertEqual(episode.snapshot_count, 2)
        self.assertEqual(episode.episode_start_lower_utc.minute, 0)
        self.assertEqual(episode.episode_start_upper_utc.minute, 5)
        self.assertEqual(episode.episode_end_lower_utc.minute, 10)
        self.assertEqual(episode.episode_end_upper_utc.minute, 15)
        self.assertEqual(episode.duration_lower_minutes, 5)
        self.assertEqual(episode.duration_upper_minutes, 15)
        self.assertEqual(episode.duration_midpoint_minutes, 10)
        self.assertFalse(episode.left_censored)
        self.assertFalse(episode.right_censored)

    def test_gap_splits_and_censors_episodes(self):
        rows = [
            snapshot(0, available=0, charging=2, zero=True),
            snapshot(5, available=0, charging=2, zero=True),
            snapshot(30, available=0, charging=2, zero=True),
        ]
        episodes = build_zero_availability_episodes(rows)
        self.assertEqual(len(episodes), 2)
        self.assertTrue(episodes[0].right_censored)
        self.assertTrue(episodes[0].ends_before_collection_gap_or_ineligible)
        self.assertTrue(episodes[1].left_censored)
        self.assertTrue(episodes[1].starts_after_collection_gap_or_ineligible)

    def test_ineligible_snapshot_breaks_episode_without_claiming_recovery(self):
        rows = [
            snapshot(0, available=1, charging=1, zero=False),
            snapshot(5, available=0, charging=2, zero=True),
            snapshot(10, available=0, charging=0, zero=None),
        ]
        episode = build_zero_availability_episodes(rows)[0]
        self.assertFalse(episode.left_censored)
        self.assertTrue(episode.right_censored)
        self.assertTrue(episode.ends_before_collection_gap_or_ineligible)

    def test_summary_reports_snapshot_share_not_queue_probability(self):
        rows = [
            snapshot(0, available=1, charging=1, zero=False),
            snapshot(5, available=0, charging=2, zero=True),
            snapshot(10, available=0, charging=2, zero=True),
            snapshot(15, available=1, charging=1, zero=False),
        ]
        summary = summarize_site_scarcity(rows)[0]
        self.assertEqual(summary.eligible_snapshot_count, 4)
        self.assertEqual(summary.zero_availability_snapshot_count, 2)
        self.assertEqual(summary.zero_availability_snapshot_share, 0.5)
        self.assertEqual(summary.zero_availability_episode_count, 1)
        self.assertEqual(summary.complete_zero_availability_episode_count, 1)
        self.assertEqual(summary.total_episode_duration_lower_minutes, 5)


if __name__ == "__main__":
    unittest.main()
