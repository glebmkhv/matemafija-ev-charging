import unittest
from datetime import datetime, timedelta, timezone

from src.adaptive_policy import (
    OsaDecisionStatus, OsaPolicyParameters, evaluate_osa_policy,
    evaluate_osa_timeline,
    osa_policy_specification,
)
from src.simulation_contract import ObservedSystemState, PolicyKind


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def state(available=0, charging=2, non_operational=0, coverage=1.0,
          evidence="auto", at=NOW):
    effective = available + charging
    offered = effective + non_operational
    if evidence == "auto":
        evidence = available == 0 if effective and coverage >= .8 else None
    return ObservedSystemState(
        ocpi_location_key="site-1", observation_time_utc=at,
        offered_evse_count=offered, available_evse_count=available,
        charging_evse_count=charging, reserved_evse_count=0,
        non_operational_evse_count=non_operational,
        indeterminate_evse_count=0, effective_operational_capacity=effective,
        availability_ratio=available/effective if effective else None,
        occupancy_proxy=charging/effective if effective else None,
        zero_availability_evidence=evidence,
        valid_observation_coverage=coverage,
    )


class OsaPolicyTest(unittest.TestCase):
    def test_default_policy_is_bounded_observable_adaptive_specification(self):
        specification = osa_policy_specification()
        self.assertEqual(specification.kind, PolicyKind.ADAPTIVE)
        self.assertEqual(specification.required_derived_statistics, ())
        self.assertEqual(specification.parameters["scarcity_trigger"], 0.5)
        self.assertEqual(specification.parameters["maximum_adjustment_eur_per_min"], .05)

    def test_full_scarcity_ramps_only_after_grace(self):
        at_grace = evaluate_osa_policy(
            state(), sustained_condition_minutes=15, f1_tariff_available=True,
        )
        halfway = evaluate_osa_policy(
            state(), sustained_condition_minutes=30, f1_tariff_available=True,
        )
        saturated = evaluate_osa_policy(
            state(), sustained_condition_minutes=60, f1_tariff_available=True,
        )
        self.assertEqual(at_grace.status, OsaDecisionStatus.INACTIVE)
        self.assertEqual(at_grace.adaptive_adjustment_eur_per_min, 0)
        self.assertEqual(halfway.adaptive_adjustment_eur_per_min, .025)
        self.assertEqual(saturated.adaptive_adjustment_eur_per_min, .05)

    def test_partial_pressure_is_nonlinear_and_bounded(self):
        parameters = OsaPolicyParameters(curvature_gamma=2)
        decision = evaluate_osa_policy(
            state(available=1, charging=3), sustained_condition_minutes=60,
            f1_tariff_available=True, parameters=parameters,
        )
        self.assertEqual(decision.status, OsaDecisionStatus.ACTIVE)
        self.assertEqual(decision.normalized_pressure, .5)
        self.assertAlmostEqual(decision.scarcity_signal, .25)
        self.assertAlmostEqual(decision.adaptive_adjustment_eur_per_min, .0125)

    def test_below_trigger_or_no_charging_is_inactive(self):
        below = evaluate_osa_policy(
            state(available=1, charging=1), sustained_condition_minutes=60,
            f1_tariff_available=True,
        )
        no_release = evaluate_osa_policy(
            state(available=2, charging=0), sustained_condition_minutes=60,
            f1_tariff_available=True,
        )
        self.assertEqual(below.reason_code, "scarcity_below_trigger")
        self.assertEqual(no_release.reason_code, "no_charging_evse_for_release_channel")
        self.assertEqual(below.adaptive_adjustment_eur_per_min, 0)

    def test_missing_tariff_or_bad_evidence_is_withheld_not_zero(self):
        no_tariff = evaluate_osa_policy(
            state(), sustained_condition_minutes=60, f1_tariff_available=False,
        )
        ineligible = evaluate_osa_policy(
            state(coverage=.5, evidence=None), sustained_condition_minutes=60,
            f1_tariff_available=True,
        )
        self.assertEqual(no_tariff.status, OsaDecisionStatus.WITHHELD)
        self.assertIsNone(no_tariff.adaptive_adjustment_eur_per_min)
        self.assertEqual(ineligible.status, OsaDecisionStatus.WITHHELD)

    def test_equipment_dominated_scarcity_is_withheld(self):
        decision = evaluate_osa_policy(
            state(available=0, charging=1, non_operational=2),
            sustained_condition_minutes=60, f1_tariff_available=True,
        )
        self.assertEqual(decision.status, OsaDecisionStatus.WITHHELD)
        self.assertEqual(decision.reason_code,
                         "equipment_unavailability_above_guard")

    def test_timeline_reconstructs_persistence_and_resets_at_gap(self):
        rows = [state(at=NOW+timedelta(minutes=minute))
                for minute in (0, 5, 10, 15, 40, 45)]
        decisions = evaluate_osa_timeline(
            rows, f1_tariff_available=True,
        )
        self.assertEqual(
            [item.sustained_condition_minutes for item in decisions],
            [0, 5, 10, 15, 0, 5],
        )
        self.assertTrue(all(item.status is OsaDecisionStatus.INACTIVE
                            for item in decisions))


if __name__ == "__main__":
    unittest.main()
