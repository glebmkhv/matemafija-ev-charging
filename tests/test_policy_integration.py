import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.adaptive_policy import OsaDecision, OsaDecisionStatus
from src.fixed_policy import (
    ObservedTariff, ReplayStatus, TariffComponent, TariffElement,
    TariffReplayResult,
)
from src.policy_integration import CompositionStatus, compose_adaptive_tariff
from src.release_response import apply_release_response, release_response_specification
from src.simulation_contract import (
    AdoptionUnit, PolicyActivationWindow, PolicyAdoptionSpecification,
)
from src.transition_model import TransitionHazardEstimate


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def tariff(currency="EUR"):
    return ObservedTariff(
        tariff_key="tariff-1", revision_id=1, currency=currency,
        tax_included=True, minimum_price=None, maximum_price=None,
        valid_from=None, valid_to=None,
        elements=(TariffElement(0, (
            TariffComponent("ENERGY", Decimal("0.30"), 1),
        )),), source_last_updated_utc=None,
    )


def f1_replay(status=ReplayStatus.CALCULATED, currency="EUR"):
    return TariffReplayResult(
        policy_id="observed_tariff_replay", policy_version="1.0.0",
        status=status, connector_key="connector-1",
        tariff_key="tariff-1" if status is ReplayStatus.CALCULATED else None,
        tariff_revision_id=1 if status is ReplayStatus.CALCULATED else None,
        currency=currency if status is ReplayStatus.CALCULATED else None,
        tax_included=True, published_total=Decimal("2.40")
        if status is ReplayStatus.CALCULATED else None,
        total_including_vat=Decimal("2.40")
        if status is ReplayStatus.CALCULATED else None,
        lines=(), datex_evidence=(), datex_price_signal_check="no_matched_datex",
        reason_codes=() if status is ReplayStatus.CALCULATED else ("missing",),
    )


def osa(status=OsaDecisionStatus.ACTIVE, adjustment=.05):
    return OsaDecision(
        ocpi_location_key="site-1", evaluation_time_utc=NOW,
        status=status, reason_code="adaptive_adjustment_active"
        if status is OsaDecisionStatus.ACTIVE else "test",
        operational_scarcity_ratio=1, normalized_pressure=1,
        sustained_condition_minutes=60, persistence_factor=1,
        scarcity_signal=1, adaptive_adjustment_eur_per_min=adjustment,
    )


def adoption(lam=.5, active=True):
    start = NOW-timedelta(minutes=5) if active else NOW+timedelta(minutes=5)
    return PolicyAdoptionSpecification(
        adoption_id="rollout", adoption_version="1", unit=AdoptionUnit.EVSE,
        price_intensity_lambda=lam, eligible_entity_ids=("evse-1",),
        treated_entity_ids=("evse-1",),
        activation_windows=(PolicyActivationWindow("evse-1", start),),
    )


def release_baseline():
    return TransitionHazardEstimate(
        channel="release_proxy", source_status="charging",
        destination_status="available", day_type="all", local_hour=None,
        exposure_hours=100, event_count=50, hazard_per_hour=.5,
        hazard_ci_lower=.37, hazard_ci_upper=.66,
        probability_per_decision_interval=.04, decision_interval_minutes=5,
        locally_qualified=True, minimum_local_event_count=3,
    )


class PolicyIntegrationTest(unittest.TestCase):
    def test_composes_f1_osa_lambda_rollout_and_release_driver(self):
        composition = compose_adaptive_tariff(
            tariff(), osa(), adoption(.5, True), connector_key="connector-1",
            entity_id="evse-1", evaluation_time_utc=NOW,
            f1_replay_result=f1_replay(),
        )
        self.assertEqual(composition.status, CompositionStatus.ACTIVE)
        self.assertEqual(composition.f1_published_total, Decimal("2.40"))
        self.assertEqual(composition.raw_adjustment_eur_per_min, Decimal("0.05"))
        self.assertEqual(composition.effective_policy_adjustment_eur_per_min,
                         Decimal("0.025"))
        self.assertEqual(composition.counterfactual_time_component_eur_per_hour,
                         Decimal("1.500"))
        self.assertIsNone(composition.counterfactual_total)

        response = apply_release_response(
            release_baseline(), [composition.response_driver],
            release_response_specification(4), entity_id="evse-1",
            evaluation_time_utc=NOW,
        )
        self.assertGreater(response.adjusted_hazard_per_hour,
                           response.baseline_hazard_per_hour)

    def test_inactive_rollout_produces_zero_driver_and_identity_response(self):
        composition = compose_adaptive_tariff(
            tariff(), osa(), adoption(.5, False), connector_key="connector-1",
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertEqual(composition.status, CompositionStatus.INACTIVE)
        self.assertEqual(composition.reason_code, "rollout_inactive")
        self.assertEqual(composition.response_driver.value, 0)
        response = apply_release_response(
            release_baseline(), [composition.response_driver],
            release_response_specification(4), entity_id="evse-1",
            evaluation_time_utc=NOW,
        )
        self.assertEqual(response.hazard_multiplier, 1)

    def test_f1_or_osa_withheld_never_becomes_zero_driver(self):
        no_f1 = compose_adaptive_tariff(
            None, osa(), adoption(), connector_key="connector-1",
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        withheld_osa = osa(OsaDecisionStatus.WITHHELD, None)
        no_osa = compose_adaptive_tariff(
            tariff(), withheld_osa, adoption(), connector_key="connector-1",
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertEqual(no_f1.status, CompositionStatus.WITHHELD)
        self.assertIsNone(no_f1.response_driver)
        self.assertEqual(no_osa.status, CompositionStatus.WITHHELD)
        self.assertIsNone(no_osa.effective_policy_adjustment_eur_per_min)

    def test_non_eur_f1_is_withheld_for_eur_adjustment(self):
        result = compose_adaptive_tariff(
            tariff(currency="USD"), osa(), adoption(), connector_key="connector-1",
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertEqual(result.status, CompositionStatus.WITHHELD)
        self.assertEqual(result.reason_code, "f1_currency_not_eur")

    def test_tariff_catalog_composes_without_inventing_session_bill(self):
        result = compose_adaptive_tariff(
            tariff(), osa(), adoption(), connector_key="connector-1",
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertEqual(result.f1_component_types, ("ENERGY",))
        self.assertIsNone(result.f1_published_total)
        self.assertEqual(result.counterfactual_total_reason,
                         "requires_observed_adjustment_duration")


if __name__ == "__main__":
    unittest.main()
