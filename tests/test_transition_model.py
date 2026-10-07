import math
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.historical import EvseStateInterval
from src.transition_model import estimate_baseline_transition_models


def interval(status, start, end, transition_to=None, **overrides):
    values = dict(
        ocpi_evse_key="evse-1", status=status,
        interval_start_lower_utc=start-timedelta(minutes=5),
        interval_start_upper_utc=start+timedelta(minutes=5),
        interval_end_lower_utc=end-timedelta(minutes=5),
        interval_end_upper_utc=end+timedelta(minutes=5),
        duration_lower_minutes=(end-start).total_seconds()/60-10,
        duration_upper_minutes=(end-start).total_seconds()/60+10,
        duration_midpoint_minutes=(end-start).total_seconds()/60,
        observation_count=2, left_censored=False, right_censored=False,
        starts_after_collection_gap=False, ends_before_collection_gap=False,
        contains_collection_gap=False, transition_from=None,
        transition_to=transition_to,
        available_to_charging_transition=False,
        charging_to_available_transition=False,
    )
    values.update(overrides)
    return EvseStateInterval(**values)


class TransitionModelTest(unittest.TestCase):
    def test_estimates_two_cause_specific_hazards_and_probabilities(self):
        start = datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
        rows = [
            interval("available", start, start+timedelta(hours=1), "charging"),
            interval("charging", start+timedelta(hours=1),
                     start+timedelta(hours=3), "available"),
        ]
        model = estimate_baseline_transition_models(
            rows, {"evse-1": "site-1"},
            {"site-1": SimpleNamespace(transition_model_ready=True)},
        )[0]
        start_estimate = model.estimate_for("charging_start_proxy", start)
        release_estimate = next(x for x in model.estimates
                                if x.channel == "release_proxy"
                                and x.day_type == "all")
        self.assertAlmostEqual(start_estimate.exposure_hours, 1)
        self.assertEqual(start_estimate.day_type, "all")
        self.assertEqual(start_estimate.event_count, 1)
        self.assertAlmostEqual(start_estimate.hazard_per_hour, 1)
        self.assertLess(start_estimate.hazard_ci_lower,
                        start_estimate.hazard_per_hour)
        self.assertGreater(start_estimate.hazard_ci_upper,
                           start_estimate.hazard_per_hour)
        self.assertAlmostEqual(start_estimate.probability_per_decision_interval,
                               1-math.exp(-1/12))
        self.assertAlmostEqual(release_estimate.exposure_hours, 2)
        self.assertAlmostEqual(release_estimate.hazard_per_hour, .5)

    def test_splits_exposure_by_vilnius_local_hour(self):
        start = datetime(2026, 10, 5, 8, 30, tzinfo=timezone.utc)
        row = interval("available", start, start+timedelta(hours=1))
        model = estimate_baseline_transition_models(
            [row], {"evse-1": "site-1"}, {"site-1": True},
        )[0]
        by_hour = {x.local_hour: x for x in model.estimates
                   if x.channel == "charging_start_proxy"
                   and x.day_type == "weekday" and x.exposure_hours}
        self.assertAlmostEqual(by_hour[11].exposure_hours, .5)
        self.assertAlmostEqual(by_hour[12].exposure_hours, .5)

    def test_excludes_censored_and_gap_affected_intervals(self):
        start = datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
        complete = interval("available", start, start+timedelta(hours=1))
        censored = interval("charging", start, start+timedelta(hours=1),
                            left_censored=True)
        gap = interval("charging", start, start+timedelta(hours=1),
                       contains_collection_gap=True)
        model = estimate_baseline_transition_models(
            [complete, censored, gap], {"evse-1": "site-1"},
            {"site-1": True},
        )[0]
        self.assertEqual(model.included_interval_count, 1)
        self.assertEqual(model.excluded_interval_count, 2)

    def test_rejects_site_that_failed_readiness_gate(self):
        start = datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "not transition-model ready"):
            estimate_baseline_transition_models(
                [interval("available", start, start+timedelta(hours=1))],
                {"evse-1": "site-1"}, {"site-1": False},
            )


if __name__ == "__main__":
    unittest.main()
