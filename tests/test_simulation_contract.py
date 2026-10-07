import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.simulation_contract import (
    BehaviouralResponseSpecification,
    ClaimScope,
    DerivedStatisticInput,
    EventType,
    ExecutionMode,
    EvseStructure,
    ObservedSystemState,
    ObservedChargingPeriod,
    ObservedChargingSession,
    PolicyKind,
    PolicySpecification,
    ProvenanceClass,
    SimulationEvent,
    SimulationRequest,
    SimulationResult,
    SiteStructure,
    observed_system_state_from_capacity_snapshot,
)
from src.flow import SiteCapacitySnapshot


NOW = datetime(2026, 10, 7, 10, tzinfo=timezone.utc)


def structure():
    return SiteStructure(
        ocpi_location_key="site-1",
        structure_version="ocpi-run-1",
        local_timezone="Europe/Vilnius",
        evses=(EvseStructure("evse-1", 1, 22.0),),
    )


def state():
    return ObservedSystemState(
        ocpi_location_key="site-1",
        observation_time_utc=NOW,
        offered_evse_count=1,
        available_evse_count=0,
        charging_evse_count=1,
        reserved_evse_count=0,
        non_operational_evse_count=0,
        indeterminate_evse_count=0,
        effective_operational_capacity=1,
        availability_ratio=0.0,
        occupancy_proxy=1.0,
        zero_availability_evidence=True,
        valid_observation_coverage=1.0,
    )


def policy(required=()):
    return PolicySpecification(
        policy_id="adaptive-observable-scarcity",
        policy_version="draft-1",
        kind=PolicyKind.ADAPTIVE,
        parameters={"base_rate_eur_per_min": 0.10},
        required_derived_statistics=required,
    )


class SimulationContractTest(unittest.TestCase):
    def test_capacity_snapshot_adapter_preserves_observable_state(self):
        snapshot = SiteCapacitySnapshot(
            collection_run_id="run-1",
            ocpi_location_key="site-1",
            observation_time_utc=NOW,
            observed_evse_count=2,
            offered_evse_count=2,
            available_evse_count=1,
            charging_evse_count=1,
            reserved_evse_count=0,
            non_operational_evse_count=0,
            unknown_evse_count=0,
            blocked_evse_count=0,
            unrecognized_status_evse_count=0,
            indeterminate_evse_count=0,
            effective_operational_capacity=2,
            occupancy_proxy=0.5,
            availability_ratio=0.5,
            zero_availability=False,
            valid_observation_coverage=1.0,
            minimum_coverage_required=0.8,
        )
        adapted = observed_system_state_from_capacity_snapshot(snapshot)
        self.assertEqual(adapted.availability_ratio, 0.5)
        self.assertFalse(adapted.zero_availability_evidence)

    def test_observed_replay_accepts_data_grounded_request(self):
        request = SimulationRequest(
            request_id="request-1",
            structure=structure(),
            observed_timeline=(state(),),
            policy=policy(),
        )
        request.validate()

    def test_tariff_session_requires_observed_meter_quantities(self):
        period = ObservedChargingPeriod(
            NOW, NOW + timedelta(minutes=30), Decimal("8.4"), 1800, 0,
            Decimal("16.8"),
        )
        session = ObservedChargingSession(
            "connector-1", NOW, NOW + timedelta(minutes=30), (period,),
        )
        request = SimulationRequest(
            request_id="request-with-session", structure=structure(),
            observed_timeline=(state(),), policy=policy(),
            observed_sessions=(session,),
        )
        request.validate()

    def test_required_statistic_must_be_present_and_qualified(self):
        statistic = DerivedStatisticInput(
            name="mean_availability_ratio",
            value=0.4,
            unit="ratio",
            estimator_version="1.0",
            training_window_start_utc=NOW - timedelta(days=8),
            training_window_end_utc=NOW,
            statistically_qualified=False,
        )
        request = SimulationRequest(
            request_id="request-1",
            structure=structure(),
            observed_timeline=(state(),),
            policy=policy(("mean_availability_ratio",)),
            derived_statistics=(statistic,),
        )
        with self.assertRaisesRegex(ValueError, "not qualified"):
            request.validate()

    def test_counterfactual_requires_validated_vilnius_response(self):
        request = SimulationRequest(
            request_id="request-1",
            structure=structure(),
            observed_timeline=(state(),),
            policy=policy(),
            execution_mode=ExecutionMode.VALIDATED_COUNTERFACTUAL,
        )
        with self.assertRaisesRegex(ValueError, "requires behavioural response"):
            request.validate()

        unvalidated = BehaviouralResponseSpecification(
            model_id="external-study",
            model_version="1",
            evidence_source="another municipality",
            validation_report="report-1",
            validated_for_vilnius=False,
            supported_outcomes=("departure_probability",),
        )
        request = SimulationRequest(
            request_id="request-2",
            structure=structure(),
            observed_timeline=(state(),),
            policy=policy(),
            execution_mode=ExecutionMode.VALIDATED_COUNTERFACTUAL,
            behavioural_response=unvalidated,
        )
        with self.assertRaisesRegex(ValueError, "validated for Vilnius"):
            request.validate()

    def test_replay_result_rejects_causal_claims_and_simulated_events(self):
        result = SimulationResult(
            request_id="request-1",
            policy_id="fixed",
            policy_version="1",
            execution_mode=ExecutionMode.OBSERVED_REPLAY,
            claim_scope=ClaimScope.MECHANISM_ONLY,
            events=(SimulationEvent(
                event_time_utc=NOW,
                event_type=EventType.COUNTERFACTUAL_CAPACITY_RELEASE,
                provenance=ProvenanceClass.SIMULATED,
            ),),
            evaluation_metrics={"capacity_released_by_fee": 2},
        )
        with self.assertRaises(ValueError):
            result.validate()

    def test_observed_state_rejects_inconsistent_capacity_partition(self):
        invalid = ObservedSystemState(
            ocpi_location_key="site-1",
            observation_time_utc=NOW,
            offered_evse_count=2,
            available_evse_count=1,
            charging_evse_count=1,
            reserved_evse_count=0,
            non_operational_evse_count=1,
            indeterminate_evse_count=0,
            effective_operational_capacity=2,
            availability_ratio=0.5,
            occupancy_proxy=0.5,
            zero_availability_evidence=False,
            valid_observation_coverage=1.0,
        )
        with self.assertRaisesRegex(ValueError, "partition"):
            invalid.validate()


if __name__ == "__main__":
    unittest.main()
