import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.simulation_contract import (
    AdoptionUnit,
    AdoptionResultMetadata,
    AssumptionDrivenResponseSpecification,
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
    PolicyActivationWindow,
    PolicyAdoptionSpecification,
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


def assumed_response():
    return AssumptionDrivenResponseSpecification(
        model_id="release-logit-shift",
        model_version="draft-1",
        functional_form="logit(q1) = logit(q0) + theta_release * price_delta",
        response_channels=("release",),
        affected_transitions=("charging_to_available",),
        parameters={"theta_release": 0.5},
        parameter_units={"theta_release": "1/EUR"},
        supported_simulated_outcomes=("simulated_availability_ratio",),
        delay_minutes=5,
    )


def adoption():
    return PolicyAdoptionSpecification(
        adoption_id="evse-rollout",
        adoption_version="draft-1",
        unit=AdoptionUnit.EVSE,
        price_intensity_lambda=0.25,
        eligible_entity_ids=("evse-1",),
        treated_entity_ids=("evse-1",),
        activation_windows=(PolicyActivationWindow("evse-1", NOW),),
    )


def adoption_summary():
    return AdoptionResultMetadata(
        adoption_id="evse-rollout", adoption_version="draft-1",
        unit=AdoptionUnit.EVSE, price_intensity_lambda=0.25,
        target_coverage_fraction_kappa=1.0,
        minimum_active_coverage_fraction=0.0,
        maximum_active_coverage_fraction=1.0,
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
            adoption=adoption(),
            behavioural_response=unvalidated,
        )
        with self.assertRaisesRegex(ValueError, "validated for Vilnius"):
            request.validate()

    def test_assumption_driven_mode_requires_assumed_response_and_seed(self):
        missing = SimulationRequest(
            request_id="assumed-1", structure=structure(),
            observed_timeline=(state(),), policy=policy(),
            execution_mode=ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL,
        )
        with self.assertRaisesRegex(ValueError, "requires an assumed response"):
            missing.validate()

        no_seed = SimulationRequest(
            request_id="assumed-2", structure=structure(),
            observed_timeline=(state(),), policy=policy(),
            execution_mode=ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL,
            assumed_response=assumed_response(), adoption=adoption(),
        )
        with self.assertRaisesRegex(ValueError, "random_seed"):
            no_seed.validate()

        valid = SimulationRequest(
            request_id="assumed-3", structure=structure(),
            observed_timeline=(state(),), policy=policy(),
            execution_mode=ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL,
            assumed_response=assumed_response(), adoption=adoption(), random_seed=42,
        )
        valid.validate()

    def test_adoption_separates_intensity_coverage_and_rollout(self):
        start = NOW
        rollout = PolicyAdoptionSpecification(
            adoption_id="two-evse-rollout", adoption_version="1",
            unit=AdoptionUnit.EVSE, price_intensity_lambda=0.5,
            eligible_entity_ids=("evse-1", "evse-2"),
            treated_entity_ids=("evse-1",),
            activation_windows=(PolicyActivationWindow(
                "evse-1", start + timedelta(minutes=10),
                start + timedelta(minutes=30),
            ),),
        )
        rollout.validate({"evse-1", "evse-2"})
        self.assertEqual(rollout.price_intensity_lambda, 0.5)
        self.assertEqual(rollout.coverage_fraction_kappa, 0.5)
        self.assertEqual(rollout.active_coverage_fraction(start), 0.0)
        self.assertEqual(rollout.rollout_state("evse-1", start + timedelta(minutes=15)), 1)
        self.assertEqual(rollout.active_coverage_fraction(start + timedelta(minutes=15)), 0.5)
        self.assertEqual(rollout.rollout_state("evse-1", start + timedelta(minutes=30)), 0)

    def test_adoption_rejects_invalid_intensity_population_and_windows(self):
        invalid_intensity = PolicyAdoptionSpecification(
            "rollout", "1", AdoptionUnit.EVSE, 1.1, ("evse-1",),
            ("evse-1",), (PolicyActivationWindow("evse-1", NOW),),
        )
        with self.assertRaisesRegex(ValueError, "between zero and one"):
            invalid_intensity.validate({"evse-1"})

        ineligible = PolicyAdoptionSpecification(
            "rollout", "1", AdoptionUnit.EVSE, 0.5, ("evse-1",),
            ("evse-2",), (PolicyActivationWindow("evse-2", NOW),),
        )
        with self.assertRaisesRegex(ValueError, "must be eligible"):
            ineligible.validate({"evse-1", "evse-2"})

    def test_assumed_parameters_cannot_be_mislabeled_as_estimated(self):
        invalid = AssumptionDrivenResponseSpecification(
            model_id="release", model_version="1", functional_form="logit_shift",
            response_channels=("release",),
            affected_transitions=("charging_to_available",),
            parameters={"theta_release": 0.5},
            parameter_units={"theta_release": "1/EUR"},
            supported_simulated_outcomes=("simulated_release_count",),
            provenance=ProvenanceClass.ESTIMATED,
        )
        with self.assertRaisesRegex(ValueError, "assumed provenance"):
            invalid.validate()

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

    def test_assumption_result_requires_conditional_scope_and_disclosure(self):
        event = SimulationEvent(
            event_time_utc=NOW,
            event_type=EventType.RESPONSE_ASSUMPTION_APPLIED,
            provenance=ProvenanceClass.ASSUMED,
            payload={"theta_release": 0.5},
        )
        valid = SimulationResult(
            request_id="assumed-3", policy_id="adaptive", policy_version="1",
            execution_mode=ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL,
            claim_scope=ClaimScope.SCENARIO_CONDITIONAL, events=(event,),
            evaluation_metrics={"simulated_availability_change": 0.1},
            adoption_summary=adoption_summary(),
            assumption_disclosure="Conditional on an assumed release response.",
            response_model_id="release-logit-shift", response_model_version="draft-1",
        )
        valid.validate()

        invalid = SimulationResult(
            request_id="assumed-3", policy_id="adaptive", policy_version="1",
            execution_mode=ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL,
            claim_scope=ClaimScope.COUNTERFACTUAL_EFFECT, events=(event,),
            evaluation_metrics={"capacity_released_by_fee": 1},
            adoption_summary=adoption_summary(),
            assumption_disclosure="Assumed.", response_model_id="release",
            response_model_version="1",
        )
        with self.assertRaises(ValueError):
            invalid.validate()

    def test_result_adoption_metadata_rejects_impossible_active_coverage(self):
        invalid = AdoptionResultMetadata(
            "rollout", "1", AdoptionUnit.EVSE, 0.5, 0.5, 0.0, 0.75,
        )
        with self.assertRaisesRegex(ValueError, "cannot exceed target"):
            invalid.validate()

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
