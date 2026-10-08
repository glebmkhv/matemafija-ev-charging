import unittest
from dataclasses import replace

from tests.test_simulation_grid import (
    adoption, decisions, estimate, model, tariff, trajectory,
)
from src.simulation_evaluation import evaluate_simulation_grid_scarcity
from src.simulation_grid import SimulationGridSpecification, run_paired_simulation_grid


def run_grid(*, intensity, theta, delay=0):
    grid = SimulationGridSpecification(
        price_intensity_values=(intensity,),
        theta_release_values=(theta,),
        response_delay_minutes_values=(delay,),
        replications=1,
        random_seed=7,
    )
    transition_model = replace(
        model(),
        estimates=(
            estimate("release_proxy", .01),
            estimate("charging_start_proxy", .2),
        ),
    )
    baseline = trajectory()
    result = run_paired_simulation_grid(
        grid, baseline, transition_model, decisions(), tariff(), adoption(),
        connector_key="connector-1", entity_id="evse-1",
    )
    return result, baseline


class SimulationEvaluationTest(unittest.TestCase):
    def test_identity_scenario_has_zero_paired_scarcity_changes(self):
        result, baseline = run_grid(intensity=0, theta=100)
        evaluation = evaluate_simulation_grid_scarcity(result, baseline).evaluations[0]
        self.assertEqual(evaluation.zero_availability_snapshot_share_change, 0)
        self.assertEqual(evaluation.mean_availability_ratio_change, 0)
        self.assertEqual(evaluation.mean_operational_scarcity_ratio_change, 0)
        self.assertFalse(evaluation.episode_metrics_applicable)

    def test_positive_release_response_improves_snapshot_scarcity(self):
        result, baseline = run_grid(intensity=1, theta=100)
        evaluation = evaluate_simulation_grid_scarcity(result, baseline).evaluations[0]
        self.assertEqual(evaluation.fixed.zero_availability_snapshot_share, 1)
        self.assertLess(evaluation.adaptive.zero_availability_snapshot_share, 1)
        self.assertLess(evaluation.zero_availability_snapshot_share_change, 0)
        self.assertGreater(evaluation.mean_availability_ratio_change, 0)
        self.assertLess(evaluation.mean_operational_scarcity_ratio_change, 0)

    def test_delay_warmup_uses_same_eligibility_mask_in_both_arms(self):
        result, baseline = run_grid(intensity=1, theta=10, delay=10)
        evaluation = evaluate_simulation_grid_scarcity(result, baseline).evaluations[0]
        self.assertEqual(evaluation.fixed.eligible_point_count, 2)
        self.assertEqual(evaluation.adaptive.eligible_point_count, 2)
        self.assertEqual(evaluation.fixed.ineligible_point_count, 2)
        self.assertEqual(evaluation.adaptive.ineligible_point_count, 2)

    def test_rejects_mismatched_trajectory(self):
        result, baseline = run_grid(intensity=1, theta=10)
        truncated = replace(baseline, points=baseline.points[:-1])
        with self.assertRaisesRegex(ValueError, "timestamps"):
            evaluate_simulation_grid_scarcity(result, truncated)

    def test_low_source_coverage_is_unknown_in_both_arms(self):
        result, baseline = run_grid(intensity=1, theta=100)
        low_coverage = replace(baseline, points=tuple(
            replace(
                point,
                source_state=replace(
                    point.source_state, valid_observation_coverage=.5,
                ),
            )
            for point in baseline.points
        ))
        evaluation = evaluate_simulation_grid_scarcity(
            result, low_coverage,
        ).evaluations[0]
        self.assertEqual(evaluation.fixed.eligible_point_count, 0)
        self.assertEqual(evaluation.adaptive.eligible_point_count, 0)
        self.assertIsNone(evaluation.zero_availability_snapshot_share_change)


if __name__ == "__main__":
    unittest.main()
