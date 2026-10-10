import unittest
from dataclasses import replace
from unittest.mock import patch

from src.credit_robustness import (
    JointRobustnessSpecification, JointRunStatus,
    calculate_joint_policy_robustness,
)
from src.credit_simulation_evaluation import evaluate_credit_simulation_grid
from src.credit_simulation_grid import run_credit_simulation_grid
from src.fairness_safety import GuardStatus
from src.robustness import RobustnessMetric
from src.simulation_evaluation import evaluate_simulation_grid_scarcity
from tests.test_credit_simulation_evaluation import available_trajectory
from tests.test_credit_simulation_grid import grid, inputs, upstream


def evaluation():
    base = upstream()
    offers, capacities = inputs(base)
    credit = run_credit_simulation_grid(base, grid(), offers, capacities)
    scarcity = evaluate_simulation_grid_scarcity(base, available_trajectory())
    return evaluate_credit_simulation_grid(credit, scarcity)


def specification(**changes):
    values = dict(
        primary_system_metric=RobustnessMetric.MEAN_AVAILABILITY,
        minimum_system_effect_size=0,
        minimum_realized_redistribution_share=.5,
        maximum_outside_unassigned_share=.5,
        maximum_mean_selected_distance_km=5,
        success_probability_threshold=.2,
        maximum_not_evaluable_share=.2,
        confidence_level=.95,
        minimum_valid_replications=1,
    )
    values.update(changes)
    return JointRobustnessSpecification(**values)


def with_distributional_pass(source):
    item = source.evaluations[0]
    updated = replace(
        item,
        redistribution=replace(
            item.redistribution,
            distributional_proxy_status=GuardStatus.PASS,
        ),
    )
    return replace(source, evaluations=(updated,))


class CreditRobustnessTest(unittest.TestCase):
    def test_not_evaluable_distribution_is_not_counted_as_success(self):
        result = calculate_joint_policy_robustness(
            evaluation(), specification(),
        )
        run = result.run_assessments[0]
        self.assertEqual(run.status, JointRunStatus.NOT_EVALUABLE)
        self.assertIsNone(run.redistribution_pass)
        summary = result.scenario_summaries[0]
        self.assertEqual(summary.valid_replication_count, 0)
        self.assertFalse(summary.observable_policy_robust)

    def test_all_observable_domains_must_pass_for_robust_scenario(self):
        result = calculate_joint_policy_robustness(
            with_distributional_pass(evaluation()), specification(),
        )
        run = result.run_assessments[0]
        self.assertEqual(run.status, JointRunStatus.SUCCESS)
        self.assertTrue(run.system_pass)
        self.assertTrue(run.redistribution_pass)
        self.assertTrue(run.user_proxy_pass)
        self.assertTrue(run.accounting_pass)
        summary = result.scenario_summaries[0]
        self.assertTrue(summary.observable_policy_robust)
        self.assertEqual(result.observable_robust_scenario_ids,
                         (summary.scenario_id,))
        self.assertFalse(summary.pilot_ready)
        self.assertFalse(summary.full_user_welfare_validated)
        self.assertFalse(summary.demographic_fairness_validated)

    def test_user_proxy_failure_cannot_be_offset_by_system_improvement(self):
        source = with_distributional_pass(evaluation())
        item = source.evaluations[0]
        source = replace(source, evaluations=(replace(
            item,
            user_proxy=replace(item.user_proxy, mean_selected_distance_km=6),
        ),))
        result = calculate_joint_policy_robustness(source, specification())
        run = result.run_assessments[0]
        self.assertTrue(run.system_pass)
        self.assertFalse(run.user_proxy_pass)
        self.assertEqual(run.status, JointRunStatus.FAILURE)
        self.assertFalse(result.scenario_summaries[0].observable_policy_robust)

    def test_strict_probability_threshold_uses_wilson_lower_bound(self):
        with patch("src.credit_robustness.NormalDist") as normal:
            normal.return_value.inv_cdf.return_value = 1.9599639845400538
            result = calculate_joint_policy_robustness(
                with_distributional_pass(evaluation()),
                specification(success_probability_threshold=.8),
            )
        summary = result.scenario_summaries[0]
        self.assertEqual(summary.success_probability, 1)
        self.assertLess(summary.success_probability_ci_lower, .8)
        self.assertFalse(summary.observable_policy_robust)

    def test_invalid_threshold_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside share"):
            specification(maximum_outside_unassigned_share=1.1).validate()


if __name__ == "__main__":
    unittest.main()
