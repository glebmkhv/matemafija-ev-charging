import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from src.simulation_contract import ObservedSystemState, ProvenanceClass
from src.trajectory import (
    TrajectoryGeneratorKind, generate_local_day_block_bootstrap,
    generate_observed_path,
)


ZONE = ZoneInfo("Europe/Vilnius")
READY = SimpleNamespace(historical_profile_ready=True)


def state(at, available):
    return ObservedSystemState(
        ocpi_location_key="site-1", observation_time_utc=at,
        offered_evse_count=2, available_evse_count=available,
        charging_evse_count=2-available, reserved_evse_count=0,
        non_operational_evse_count=0, indeterminate_evse_count=0,
        effective_operational_capacity=2,
        availability_ratio=available/2, occupancy_proxy=(2-available)/2,
        zero_availability_evidence=available == 0,
        valid_observation_coverage=1.0,
    )


def full_day(local_date, marker):
    rows = []
    for hour in range(24):
        local = datetime.combine(local_date, datetime.min.time(), ZONE) + timedelta(hours=hour)
        rows.append(state(local.astimezone(timezone.utc), (hour+marker) % 3))
    return rows


class TrajectoryGeneratorTest(unittest.TestCase):
    def test_observed_path_is_exact_and_reconstructed(self):
        rows = full_day(date(2026, 10, 5), 0)
        trajectory = generate_observed_path(rows)
        self.assertEqual(trajectory.generator_kind,
                         TrajectoryGeneratorKind.OBSERVED_PATH)
        self.assertIsNone(trajectory.random_seed)
        self.assertEqual(
            [point.trajectory_time_utc for point in trajectory.points],
            [row.observation_time_utc for row in rows],
        )
        self.assertTrue(all(point.provenance is ProvenanceClass.RECONSTRUCTED
                            for point in trajectory.points))

    def test_bootstrap_is_seeded_and_preserves_whole_snapshot_vectors(self):
        rows = (
            full_day(date(2026, 10, 5), 0)
            + full_day(date(2026, 10, 6), 1)
            + full_day(date(2026, 10, 10), 2)
        )
        kwargs = dict(
            target_start_local_date=date(2026, 10, 12), horizon_days=7,
            random_seed=17, readiness=READY, expected_cadence_seconds=3600,
        )
        first = generate_local_day_block_bootstrap(rows, **kwargs)
        second = generate_local_day_block_bootstrap(rows, **kwargs)
        self.assertEqual(first.sampled_blocks, second.sampled_blocks)
        self.assertEqual(len(first.points), 7*24)
        self.assertTrue(all(point.provenance is ProvenanceClass.SIMULATED
                            for point in first.points))
        self.assertTrue(all(
            point.source_state.available_evse_count
            + point.source_state.charging_evse_count == 2
            for point in first.points
        ))
        self.assertEqual(
            [block.day_type for block in first.sampled_blocks],
            ["weekday"]*5 + ["weekend"]*2,
        )

    def test_rejects_bootstrap_without_qualified_day_type_pool(self):
        rows = full_day(date(2026, 10, 5), 0)
        with self.assertRaisesRegex(ValueError, "weekend"):
            generate_local_day_block_bootstrap(
                rows, target_start_local_date=date(2026, 10, 10),
                horizon_days=1, random_seed=1, readiness=READY,
                expected_cadence_seconds=3600,
            )

    def test_partial_day_is_not_a_qualified_block(self):
        rows = full_day(date(2026, 10, 5), 0)[:10]
        with self.assertRaisesRegex(ValueError, "weekday"):
            generate_local_day_block_bootstrap(
                rows, target_start_local_date=date(2026, 10, 12),
                horizon_days=1, random_seed=1, readiness=READY,
                expected_cadence_seconds=3600,
            )

    def test_bootstrap_rejects_unqualified_history(self):
        rows = full_day(date(2026, 10, 5), 0)
        with self.assertRaisesRegex(ValueError, "historical_profile_ready"):
            generate_local_day_block_bootstrap(
                rows, target_start_local_date=date(2026, 10, 12),
                horizon_days=1, random_seed=1, readiness=False,
                expected_cadence_seconds=3600,
            )


if __name__ == "__main__":
    unittest.main()
