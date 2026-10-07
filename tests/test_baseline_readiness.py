import unittest
from datetime import datetime, timedelta, timezone

from src.baseline_readiness import (
    SiteReadinessMetadata, assess_baseline_readiness,
    summarize_baseline_readiness,
)
from src.flow import SiteCapacitySnapshot
from src.historical import EvseStateInterval


START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def snapshot(at, available, charging):
    effective = available + charging
    return SiteCapacitySnapshot(
        collection_run_id=f"run-{at.isoformat()}", ocpi_location_key="site-1",
        observation_time_utc=at, observed_evse_count=effective,
        offered_evse_count=effective, available_evse_count=available,
        charging_evse_count=charging, reserved_evse_count=0,
        non_operational_evse_count=0, unknown_evse_count=0,
        blocked_evse_count=0, unrecognized_status_evse_count=0,
        indeterminate_evse_count=0, effective_operational_capacity=effective,
        occupancy_proxy=charging/effective, availability_ratio=available/effective,
        zero_availability=available == 0, valid_observation_coverage=1.0,
        minimum_coverage_required=0.8,
    )


def interval(index, start_transition=False, release_transition=False):
    at = START + timedelta(hours=index)
    status = ("available" if start_transition else
              "charging" if release_transition else
              ("charging" if index % 2 else "available"))
    return EvseStateInterval(
        ocpi_evse_key="evse-1", status=status,
        interval_start_lower_utc=at-timedelta(minutes=5),
        interval_start_upper_utc=at, interval_end_lower_utc=at+timedelta(minutes=5),
        interval_end_upper_utc=at+timedelta(minutes=10),
        duration_lower_minutes=5, duration_upper_minutes=15,
        duration_midpoint_minutes=10, observation_count=2,
        left_censored=False, right_censored=False,
        starts_after_collection_gap=False, ends_before_collection_gap=False,
        contains_collection_gap=False,
        transition_from="available" if start_transition else
                        ("charging" if release_transition else None),
        transition_to="charging" if start_transition else
                      ("available" if release_transition else None),
        available_to_charging_transition=start_transition,
        charging_to_available_transition=release_transition,
    )


class BaselineReadinessTest(unittest.TestCase):
    def test_qualified_history_transitions_and_tariff_are_simulation_ready(self):
        snapshots=[]
        for hour in range(8*24+1):
            snapshots.append(snapshot(START+timedelta(hours=hour), hour%2, 2-(hour%2)))
        intervals=[]
        for index in range(40):
            intervals.append(interval(index, start_transition=index<20,
                                      release_transition=index>=20))
        metadata={"site-1":SiteReadinessMetadata(
            "site-1",1,1,1,("ENERGY",),1)}
        result=assess_baseline_readiness(
            snapshots,intervals,{"evse-1":"site-1"},metadata,
            expected_cadence_seconds=3600,
        )[0]
        self.assertTrue(result.transition_model_ready)
        self.assertTrue(result.f1_tariff_ready)
        self.assertTrue(result.assumption_driven_simulation_ready)
        self.assertEqual(result.readiness_tier,"assumption_driven_simulation_ready")

    def test_short_history_remains_descriptive_and_reports_blockers(self):
        snapshots=[snapshot(START+timedelta(hours=h),1,1) for h in range(24)]
        metadata={"site-1":SiteReadinessMetadata("site-1",1,1,0,(),0)}
        result=assess_baseline_readiness(
            snapshots,[],{},metadata,expected_cadence_seconds=3600,
        )[0]
        self.assertTrue(result.descriptive_replay_ready)
        self.assertFalse(result.historical_profile_ready)
        self.assertFalse(result.assumption_driven_simulation_ready)
        self.assertEqual(result.readiness_tier,"descriptive_only")
        self.assertIn("history_span_below_7_days",result.blocking_reasons)
        self.assertIn("no_observed_tariff_components",result.blocking_reasons)
        self.assertIn("no_matched_datex_station_for_corroboration",result.warnings)

    def test_summary_counts_each_gate_separately(self):
        snapshots=[snapshot(START+timedelta(hours=h),1,1) for h in range(24)]
        rows=assess_baseline_readiness(
            snapshots,[],{},
            {"site-1":SiteReadinessMetadata("site-1",1,1,1,("ENERGY",),1)},
            expected_cadence_seconds=3600,
        )
        summary=summarize_baseline_readiness(rows)
        self.assertEqual(summary.site_count,1)
        self.assertEqual(summary.descriptive_replay_ready_count,1)
        self.assertEqual(summary.f1_tariff_ready_count,1)
        self.assertEqual(summary.transition_model_ready_count,0)


if __name__=="__main__": unittest.main()
