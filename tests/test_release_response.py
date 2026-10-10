import unittest
from datetime import datetime, timedelta, timezone

from src.release_response import (
    ORIGIN_PRICE_SIGNAL_NAME, ORIGIN_PRICE_SIGNAL_UNIT,
    RELEASE_CREDIT_SIGNAL_NAME, RELEASE_CREDIT_SIGNAL_UNIT,
    RELEASE_DRIVER_NAME, RELEASE_DRIVER_UNIT, apply_release_response,
    apply_release_response_v2, release_response_specification,
    release_response_v2_specification, typed_price_signal_from_v1,
)
from src.simulation_contract import (
    ProvenanceClass, ResponseDriverPoint, ResponseSignalState,
    TypedResponseSignalPoint,
)
from src.transition_model import TransitionHazardEstimate


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def baseline(channel="release_proxy", qualified=True):
    return TransitionHazardEstimate(
        channel=channel,
        source_status="charging" if channel == "release_proxy" else "available",
        destination_status="available" if channel == "release_proxy" else "charging",
        day_type="all", local_hour=None, exposure_hours=100,
        event_count=50, hazard_per_hour=0.5,
        hazard_ci_lower=0.37, hazard_ci_upper=0.66,
        probability_per_decision_interval=1-(2.718281828459045 ** (-0.5/12)),
        decision_interval_minutes=5, locally_qualified=qualified,
        minimum_local_event_count=3,
    )


def driver(at, value, entity="evse-1"):
    return ResponseDriverPoint(
        entity_id=entity, effective_at_utc=at,
        driver_name=RELEASE_DRIVER_NAME, driver_unit=RELEASE_DRIVER_UNIT,
        value=value,
    )


def typed_signal(
    at, value, *, name=ORIGIN_PRICE_SIGNAL_NAME,
    unit=ORIGIN_PRICE_SIGNAL_UNIT, entity="evse-1",
    state=ResponseSignalState.AVAILABLE,
    provenance=ProvenanceClass.POLICY_DEFINED, reason=None,
):
    return TypedResponseSignalPoint(
        entity_id=entity, effective_at_utc=at, signal_name=name,
        signal_unit=unit, state=state, value=value,
        source_event_id=f"event:{name}:{at.isoformat()}",
        reason_code=reason, provenance=provenance,
    )


class ReleaseResponseTest(unittest.TestCase):
    def test_zero_driver_is_exact_identity(self):
        result = apply_release_response(
            baseline(), [driver(NOW, 0)], release_response_specification(4),
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertEqual(result.hazard_multiplier, 1)
        self.assertEqual(result.adjusted_hazard_per_hour,
                         result.baseline_hazard_per_hour)
        self.assertEqual(result.adjusted_release_probability,
                         result.baseline_release_probability)

    def test_positive_driver_increases_release_monotonically_and_stays_bounded(self):
        specification = release_response_specification(4)
        low = apply_release_response(
            baseline(), [driver(NOW, .05)], specification,
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        high = apply_release_response(
            baseline(), [driver(NOW, .10)], specification,
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertGreater(low.adjusted_hazard_per_hour, low.baseline_hazard_per_hour)
        self.assertGreater(high.adjusted_hazard_per_hour, low.adjusted_hazard_per_hour)
        self.assertGreater(high.adjusted_release_probability,
                           low.adjusted_release_probability)
        self.assertLess(high.adjusted_release_probability, 1)

    def test_negative_driver_reduces_release_without_negative_probability(self):
        result = apply_release_response(
            baseline(), [driver(NOW, -.10)], release_response_specification(4),
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertLess(result.adjusted_hazard_per_hour,
                        result.baseline_hazard_per_hour)
        self.assertGreaterEqual(result.adjusted_release_probability, 0)

    def test_delay_uses_latest_driver_not_after_cutoff(self):
        points = [
            driver(NOW-timedelta(minutes=20), .02),
            driver(NOW-timedelta(minutes=10), .08),
            driver(NOW, .20),
        ]
        result = apply_release_response(
            baseline(), points, release_response_specification(4, delay_minutes=15),
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertEqual(result.driver_time_utc, NOW-timedelta(minutes=20))
        self.assertEqual(result.driver_value, .02)

    def test_rejects_missing_delayed_driver_and_wrong_baseline_channel(self):
        specification = release_response_specification(4, delay_minutes=15)
        with self.assertRaisesRegex(ValueError, "No response driver"):
            apply_release_response(
                baseline(), [driver(NOW-timedelta(minutes=10), .1)], specification,
                entity_id="evse-1", evaluation_time_utc=NOW,
            )
        with self.assertRaisesRegex(ValueError, "charging-to-available"):
            apply_release_response(
                baseline("charging_start_proxy"), [driver(NOW, .1)],
                release_response_specification(4), entity_id="evse-1",
                evaluation_time_utc=NOW,
            )

    def test_rejects_unqualified_baseline(self):
        with self.assertRaisesRegex(ValueError, "qualified baseline"):
            apply_release_response(
                baseline(qualified=False), [driver(NOW, .1)],
                release_response_specification(4), entity_id="evse-1",
                evaluation_time_utc=NOW,
            )


class ReleaseResponseV2Test(unittest.TestCase):
    def test_price_only_zero_signal_is_exact_identity(self):
        result = apply_release_response_v2(
            baseline(), [typed_signal(NOW, 0)],
            release_response_v2_specification(4),
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertEqual(result.total_exponent, 0)
        self.assertEqual(result.hazard_multiplier, 1)
        self.assertEqual(result.adjusted_hazard_per_hour,
                         result.baseline_hazard_per_hour)
        self.assertIsNone(result.credit_signal_value_mcu)

    def test_price_and_credit_have_separate_components_and_delays(self):
        price_points = [
            typed_signal(NOW-timedelta(minutes=20), .05),
            typed_signal(NOW, .20),
        ]
        credit_points = [
            typed_signal(
                NOW-timedelta(minutes=10), 10,
                name=RELEASE_CREDIT_SIGNAL_NAME,
                unit=RELEASE_CREDIT_SIGNAL_UNIT,
                provenance=ProvenanceClass.SIMULATED,
            ),
            typed_signal(
                NOW, 20, name=RELEASE_CREDIT_SIGNAL_NAME,
                unit=RELEASE_CREDIT_SIGNAL_UNIT,
                provenance=ProvenanceClass.SIMULATED,
            ),
        ]
        result = apply_release_response_v2(
            baseline(), price_points,
            release_response_v2_specification(
                4, theta_release_credit=.02,
                delay_release_price_minutes=15,
                delay_release_credit_minutes=5,
                release_credit_applicable=True,
            ),
            entity_id="evse-1", evaluation_time_utc=NOW,
            credit_signal_points=credit_points,
        )
        self.assertAlmostEqual(result.price_exponent_component, .2)
        self.assertAlmostEqual(result.credit_exponent_component, .2)
        self.assertAlmostEqual(result.total_exponent, .4)
        self.assertEqual(result.price_signal_time_utc, NOW-timedelta(minutes=20))
        self.assertEqual(result.credit_signal_time_utc, NOW-timedelta(minutes=10))
        self.assertGreater(result.adjusted_release_probability,
                           result.baseline_release_probability)

    def test_credit_monotonicity_with_fixed_price(self):
        specification = release_response_v2_specification(
            4, theta_release_credit=.03, release_credit_applicable=True,
        )
        price = [typed_signal(NOW, .05)]
        def credit(value):
            return [typed_signal(
                NOW, value, name=RELEASE_CREDIT_SIGNAL_NAME,
                unit=RELEASE_CREDIT_SIGNAL_UNIT,
                provenance=ProvenanceClass.SIMULATED,
            )]
        low = apply_release_response_v2(
            baseline(), price, specification, entity_id="evse-1",
            evaluation_time_utc=NOW, credit_signal_points=credit(1),
        )
        high = apply_release_response_v2(
            baseline(), price, specification, entity_id="evse-1",
            evaluation_time_utc=NOW, credit_signal_points=credit(10),
        )
        self.assertGreater(high.adjusted_hazard_per_hour,
                           low.adjusted_hazard_per_hour)

    def test_non_applicable_credit_cannot_hide_active_offer(self):
        active_credit = typed_signal(
            NOW, 5, name=RELEASE_CREDIT_SIGNAL_NAME,
            unit=RELEASE_CREDIT_SIGNAL_UNIT,
            provenance=ProvenanceClass.SIMULATED,
        )
        with self.assertRaisesRegex(ValueError, "cannot ignore an active signal"):
            apply_release_response_v2(
                baseline(), [typed_signal(NOW, .05)],
                release_response_v2_specification(4),
                entity_id="evse-1", evaluation_time_utc=NOW,
                credit_signal_points=[active_credit],
            )

    def test_withheld_price_and_credit_are_not_zero(self):
        withheld_price = typed_signal(
            NOW, None, state=ResponseSignalState.WITHHELD,
            reason="tariff_missing",
        )
        with self.assertRaisesRegex(ValueError, "price signal is withheld"):
            apply_release_response_v2(
                baseline(), [withheld_price],
                release_response_v2_specification(4),
                entity_id="evse-1", evaluation_time_utc=NOW,
            )
        withheld_credit = typed_signal(
            NOW, None, name=RELEASE_CREDIT_SIGNAL_NAME,
            unit=RELEASE_CREDIT_SIGNAL_UNIT,
            state=ResponseSignalState.WITHHELD,
            provenance=ProvenanceClass.SIMULATED,
            reason="pool_unavailable",
        )
        with self.assertRaisesRegex(ValueError, "credit signal is withheld"):
            apply_release_response_v2(
                baseline(), [typed_signal(NOW, .05)],
                release_response_v2_specification(
                    4, theta_release_credit=.02,
                    release_credit_applicable=True,
                ),
                entity_id="evse-1", evaluation_time_utc=NOW,
                credit_signal_points=[withheld_credit],
            )

    def test_credit_requires_integer_mcu(self):
        fractional_credit = typed_signal(
            NOW, 1.5, name=RELEASE_CREDIT_SIGNAL_NAME,
            unit=RELEASE_CREDIT_SIGNAL_UNIT,
            provenance=ProvenanceClass.SIMULATED,
        )
        with self.assertRaisesRegex(ValueError, "integer MCU"):
            apply_release_response_v2(
                baseline(), [typed_signal(NOW, .05)],
                release_response_v2_specification(
                    4, theta_release_credit=.02,
                    release_credit_applicable=True,
                ),
                entity_id="evse-1", evaluation_time_utc=NOW,
                credit_signal_points=[fractional_credit],
            )

    def test_v1_adapter_preserves_value_and_withheld_state(self):
        mapped = typed_price_signal_from_v1(driver(NOW, .07))
        self.assertEqual(mapped.signal_name, ORIGIN_PRICE_SIGNAL_NAME)
        self.assertEqual(mapped.value, .07)
        withheld = typed_price_signal_from_v1(ResponseDriverPoint(
            entity_id="evse-1", effective_at_utc=NOW,
            driver_name=RELEASE_DRIVER_NAME, driver_unit=RELEASE_DRIVER_UNIT,
            value=None, withheld=True, reason_code="osa_withheld",
        ))
        self.assertEqual(withheld.state, ResponseSignalState.WITHHELD)
        self.assertIsNone(withheld.value)


if __name__ == "__main__":
    unittest.main()
