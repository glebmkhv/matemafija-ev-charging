import unittest
from datetime import datetime, timezone

from src.arrival_response import (
    ARRIVAL_DRIVER_NAME, ARRIVAL_DRIVER_UNIT, apply_arrival_response,
    arrival_response_specification,
)
from src.simulation_contract import ResponseDriverPoint
from src.transition_model import TransitionHazardEstimate


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def baseline(channel="charging_start_proxy", qualified=True):
    return TransitionHazardEstimate(
        channel=channel,
        source_status="available" if channel == "charging_start_proxy" else "charging",
        destination_status="charging" if channel == "charging_start_proxy" else "available",
        day_type="all", local_hour=None, exposure_hours=100, event_count=50,
        hazard_per_hour=.5, hazard_ci_lower=.3, hazard_ci_upper=.7,
        probability_per_decision_interval=1-__import__("math").exp(-.5/12),
        decision_interval_minutes=5, locally_qualified=qualified,
        minimum_local_event_count=3,
    )


def driver(value):
    return ResponseDriverPoint(
        entity_id="evse-1", effective_at_utc=NOW,
        driver_name=ARRIVAL_DRIVER_NAME, driver_unit=ARRIVAL_DRIVER_UNIT,
        value=value,
    )


class ArrivalResponseTest(unittest.TestCase):
    def test_zero_driver_is_identity(self):
        result = apply_arrival_response(
            baseline(), [driver(0)], arrival_response_specification(10),
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertEqual(result.hazard_multiplier, 1)
        self.assertEqual(result.adjusted_start_probability,
                         result.baseline_start_probability)

    def test_positive_adjustment_reduces_start_probability(self):
        low = apply_arrival_response(
            baseline(), [driver(.02)], arrival_response_specification(10),
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        high = apply_arrival_response(
            baseline(), [driver(.05)], arrival_response_specification(10),
            entity_id="evse-1", evaluation_time_utc=NOW,
        )
        self.assertLess(low.adjusted_start_probability,
                        low.baseline_start_probability)
        self.assertLess(high.adjusted_start_probability,
                        low.adjusted_start_probability)

    def test_rejects_wrong_or_unqualified_baseline(self):
        with self.assertRaisesRegex(ValueError, "available-to-charging"):
            apply_arrival_response(
                baseline("release_proxy"), [driver(.05)],
                arrival_response_specification(10), entity_id="evse-1",
                evaluation_time_utc=NOW,
            )
        with self.assertRaisesRegex(ValueError, "qualified baseline"):
            apply_arrival_response(
                baseline(qualified=False), [driver(.05)],
                arrival_response_specification(10), entity_id="evse-1",
                evaluation_time_utc=NOW,
            )


if __name__ == "__main__":
    unittest.main()
