import unittest
from datetime import datetime, timedelta, timezone

from src.release_response import (
    RELEASE_DRIVER_NAME, RELEASE_DRIVER_UNIT, apply_release_response,
    release_response_specification,
)
from src.simulation_contract import ResponseDriverPoint
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


if __name__ == "__main__":
    unittest.main()
