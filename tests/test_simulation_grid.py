import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.adaptive_policy import OsaDecision, OsaDecisionStatus
from src.fixed_policy import ObservedTariff, TariffComponent, TariffElement
from src.simulation_contract import (
    AdoptionUnit, ObservedSystemState, PolicyActivationWindow,
    PolicyAdoptionSpecification, ProvenanceClass,
)
from src.simulation_grid import SimulationGridSpecification, run_paired_simulation_grid
from src.trajectory import BaselineTrajectory, TrajectoryGeneratorKind, TrajectoryPoint
from src.transition_model import SiteTransitionModel, TransitionHazardEstimate


START = datetime(2026, 10, 8, 10, tzinfo=timezone.utc)


def system_state(at):
    return ObservedSystemState(
        ocpi_location_key="site-1", observation_time_utc=at,
        offered_evse_count=4, available_evse_count=0, charging_evse_count=4,
        reserved_evse_count=0, non_operational_evse_count=0,
        indeterminate_evse_count=0, effective_operational_capacity=4,
        availability_ratio=0, occupancy_proxy=1,
        zero_availability_evidence=True, valid_observation_coverage=1,
    )


def trajectory():
    points = []
    for index in range(4):
        at = START + timedelta(minutes=5*index)
        state = system_state(at)
        points.append(TrajectoryPoint(at, at, state, ProvenanceClass.RECONSTRUCTED))
    return BaselineTrajectory(
        ocpi_location_key="site-1", local_timezone="Europe/Vilnius",
        generator_kind=TrajectoryGeneratorKind.OBSERVED_PATH,
        points=tuple(points),
    )


def estimate(channel, probability):
    hazard = -12 * __import__("math").log(1-probability)
    return TransitionHazardEstimate(
        channel=channel,
        source_status="charging" if channel == "release_proxy" else "available",
        destination_status="available" if channel == "release_proxy" else "charging",
        day_type="all", local_hour=None, exposure_hours=100, event_count=20,
        hazard_per_hour=hazard, hazard_ci_lower=0, hazard_ci_upper=1,
        probability_per_decision_interval=probability,
        decision_interval_minutes=5, locally_qualified=True,
        minimum_local_event_count=3,
    )


def model():
    return SiteTransitionModel(
        ocpi_location_key="site-1", local_timezone="Europe/Vilnius",
        training_start_utc=(START-timedelta(days=8)).isoformat(),
        training_end_utc=START.isoformat(), included_interval_count=100,
        excluded_interval_count=0,
        estimates=(estimate("release_proxy", .2), estimate("charging_start_proxy", .2)),
    )


def decisions():
    return tuple(OsaDecision(
        ocpi_location_key="site-1", evaluation_time_utc=point.trajectory_time_utc,
        status=OsaDecisionStatus.ACTIVE, reason_code="adaptive_adjustment_active",
        operational_scarcity_ratio=1, normalized_pressure=1,
        sustained_condition_minutes=60, persistence_factor=1,
        scarcity_signal=1, adaptive_adjustment_eur_per_min=.05,
    ) for point in trajectory().points)


def tariff():
    return ObservedTariff(
        tariff_key="tariff-1", revision_id=1, currency="EUR", tax_included=True,
        minimum_price=None, maximum_price=None, valid_from=None, valid_to=None,
        elements=(TariffElement(0, (TariffComponent(
            "ENERGY", Decimal("0.3"), 1,
        ),)),), source_last_updated_utc=None,
    )


def adoption():
    return PolicyAdoptionSpecification(
        adoption_id="rollout", adoption_version="1", unit=AdoptionUnit.EVSE,
        price_intensity_lambda=1, eligible_entity_ids=("evse-1",),
        treated_entity_ids=("evse-1",),
        activation_windows=(PolicyActivationWindow("evse-1", START),),
    )


class SimulationGridTest(unittest.TestCase):
    def test_grid_is_reproducible_and_uses_paired_common_random_numbers(self):
        grid = SimulationGridSpecification(
            price_intensity_values=(0, 1), theta_release_values=(0, 20),
            response_delay_minutes_values=(0,), replications=3, random_seed=7,
        )
        kwargs = dict(
            grid=grid, trajectory=trajectory(), transition_model=model(),
            osa_decisions=decisions(), f1_tariff=tariff(),
            adoption_template=adoption(), connector_key="connector-1",
            entity_id="evse-1",
        )
        first = run_paired_simulation_grid(**kwargs)
        second = run_paired_simulation_grid(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(len(first.runs), 2*2*1*3)
        for run in first.runs:
            if run.scenario.price_intensity_lambda == 0 or run.scenario.theta_release == 0:
                self.assertEqual(run.fixed_release_count, run.adaptive_release_count)
            else:
                self.assertGreaterEqual(run.adaptive_release_count,
                                        run.fixed_release_count)
            self.assertTrue(run.common_random_numbers)

    def test_delay_withholds_only_points_without_signal_history(self):
        grid = SimulationGridSpecification(
            price_intensity_values=(1,), theta_release_values=(5,),
            response_delay_minutes_values=(10,), replications=1, random_seed=3,
        )
        result = run_paired_simulation_grid(
            grid, trajectory(), model(), decisions(), tariff(), adoption(),
            connector_key="connector-1", entity_id="evse-1",
        )
        run = result.runs[0]
        self.assertEqual(run.withheld_point_count, 2)
        self.assertEqual(run.eligible_point_count, 2)
        self.assertEqual(run.points[0].reason_code,
                         "delayed_driver_history_unavailable")

    def test_grid_rejects_invalid_lambda(self):
        with self.assertRaisesRegex(ValueError, "lambda"):
            SimulationGridSpecification(
                price_intensity_values=(1.2,), theta_release_values=(1,),
                response_delay_minutes_values=(0,), replications=1, random_seed=1,
            ).validate()

    def test_decision_generator_is_consumed_once(self):
        grid = SimulationGridSpecification(
            price_intensity_values=(0,), theta_release_values=(0,),
            response_delay_minutes_values=(0,), replications=1, random_seed=1,
        )
        result = run_paired_simulation_grid(
            grid, trajectory(), model(), (item for item in decisions()),
            tariff(), adoption(), connector_key="connector-1",
            entity_id="evse-1",
        )
        self.assertEqual(result.runs[0].eligible_point_count, 4)

    def test_arrival_response_reduces_accepted_start_proxy(self):
        available_trajectory = trajectory()
        available_trajectory = replace(
            available_trajectory,
            points=tuple(replace(
                point,
                source_state=replace(
                    point.source_state,
                    available_evse_count=4,
                    charging_evse_count=0,
                    availability_ratio=1,
                    occupancy_proxy=0,
                    zero_availability_evidence=False,
                ),
            ) for point in available_trajectory.points),
        )
        grid = SimulationGridSpecification(
            price_intensity_values=(1,), theta_release_values=(0,),
            response_delay_minutes_values=(0,), replications=3, random_seed=7,
            theta_arrival_values=(20,),
        )
        result = run_paired_simulation_grid(
            grid, available_trajectory, model(), decisions(), tariff(), adoption(),
            connector_key="connector-1", entity_id="evse-1",
        )
        for run in result.runs:
            self.assertLessEqual(run.adaptive_start_count, run.fixed_start_count)
            self.assertEqual(
                run.deferred_or_displaced_start_proxy_count,
                run.fixed_start_count-run.adaptive_start_count,
            )
            self.assertEqual(
                len(run.redistribution_candidates),
                run.deferred_or_displaced_start_proxy_count,
            )
            for candidate in run.redistribution_candidates:
                self.assertEqual(candidate.scenario_id, run.scenario.scenario_id)
                self.assertEqual(candidate.replication_index, run.replication_index)
                self.assertLess(candidate.paired_uniform,
                                candidate.baseline_start_probability)
                self.assertGreaterEqual(candidate.paired_uniform,
                                        candidate.adaptive_start_probability)


if __name__ == "__main__":
    unittest.main()
