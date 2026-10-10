import unittest
from unittest.mock import patch

from src.robustness import (
    RobustnessSpecification,
    calculate_robustness_region,
)
from src.simulation_contract import ClaimScope, ProvenanceClass
from src.simulation_evaluation import (
    PairedScarcityEvaluation,
    ProjectedScarcitySummary,
    SimulationGridEvaluation,
)
from src.simulation_grid import SimulationGridSpecification, SimulationScenario


def projected(zero_count, *, eligible=10, availability=.5):
    return ProjectedScarcitySummary(
        total_point_count=eligible,
        eligible_point_count=eligible,
        ineligible_point_count=0,
        zero_availability_point_count=zero_count,
        zero_availability_snapshot_share=zero_count / eligible,
        mean_availability_ratio=availability,
        mean_operational_scarcity_ratio=1-availability,
    )


def evaluation(scenario, replication, *, improved):
    fixed = projected(5, availability=.5)
    adaptive = projected(
        4 if improved else 5,
        availability=.6 if improved else .5,
    )
    return PairedScarcityEvaluation(
        scenario=scenario,
        replication_index=replication,
        random_seed=100+replication,
        fixed=fixed,
        adaptive=adaptive,
        zero_availability_snapshot_share_change=(
            adaptive.zero_availability_snapshot_share
            - fixed.zero_availability_snapshot_share
        ),
        mean_availability_ratio_change=(
            adaptive.mean_availability_ratio - fixed.mean_availability_ratio
        ),
        mean_operational_scarcity_ratio_change=(
            adaptive.mean_operational_scarcity_ratio
            - fixed.mean_operational_scarcity_ratio
        ),
        fixed_start_proxy_count=5,
        adaptive_start_proxy_count=4 if improved else 5,
        deferred_or_displaced_start_proxy_count=1 if improved else 0,
        claim_scope=ClaimScope.SCENARIO_CONDITIONAL,
        provenance=ProvenanceClass.SIMULATED,
    )


def grid_evaluation(replications=20):
    grid = SimulationGridSpecification(
        price_intensity_values=(1,),
        theta_release_values=(0, 100),
        response_delay_minutes_values=(0,),
        replications=replications,
        random_seed=100,
    )
    baseline = SimulationScenario("lambda=1|theta_r=0|tau=0", 1, 0, 0)
    response = SimulationScenario("lambda=1|theta_r=100|tau=0", 1, 100, 0)
    rows = []
    for scenario in (baseline, response):
        for replication in range(replications):
            rows.append(evaluation(
                scenario,
                replication,
                improved=scenario.theta_release > 0,
            ))
    return SimulationGridEvaluation(
        grid=grid,
        evaluations=tuple(rows),
        simulation_grid_version="1.0.0",
        baseline_generator_kind="observed_path",
        baseline_generator_version="1.0.0",
        transition_model_version="1.0.0",
        minimum_coverage_required=.8,
    )


class RobustnessTest(unittest.TestCase):
    def test_finds_robust_region_and_minimum_tested_theta(self):
        # This z value reproduces the one-ulp inward Wilson endpoint observed
        # on the GitHub Ubuntu runner for all-failure/all-success samples.
        with patch("src.robustness.NormalDist") as normal:
            normal.return_value.inv_cdf.return_value = 1.9599639845400538
            result = calculate_robustness_region(grid_evaluation())
        by_theta = {
            row.scenario.theta_release: row
            for row in result.scenario_summaries
        }
        self.assertFalse(by_theta[0].empirically_successful)
        self.assertFalse(by_theta[0].robust_success)
        self.assertEqual(by_theta[0].improvement_probability_ci_lower, 0)
        self.assertEqual(by_theta[100].improvement_probability, 1)
        self.assertEqual(by_theta[100].improvement_probability_ci_upper, 1)
        self.assertGreater(by_theta[100].improvement_probability_ci_lower, .8)
        self.assertTrue(by_theta[100].robust_success)
        threshold = result.minimum_response_thresholds[0]
        self.assertTrue(threshold.identified_on_grid)
        self.assertEqual(threshold.minimum_tested_theta_release, 100)

    def test_empirical_success_is_not_robust_with_too_little_evidence(self):
        result = calculate_robustness_region(
            grid_evaluation(replications=5),
            RobustnessSpecification(minimum_valid_replications=5),
        )
        response = next(
            row for row in result.scenario_summaries
            if row.scenario.theta_release == 100
        )
        self.assertTrue(response.empirically_successful)
        self.assertFalse(response.robust_success)
        self.assertFalse(result.minimum_response_thresholds[0].identified_on_grid)

    def test_minimum_effect_size_is_strict(self):
        result = calculate_robustness_region(
            grid_evaluation(),
            RobustnessSpecification(minimum_effect_size=.1),
        )
        response = next(
            row for row in result.scenario_summaries
            if row.scenario.theta_release == 100
        )
        self.assertEqual(response.improvement_count, 0)

    def test_rejects_incomplete_grid(self):
        source = grid_evaluation()
        incomplete = SimulationGridEvaluation(
            grid=source.grid,
            evaluations=source.evaluations[:-1],
            simulation_grid_version=source.simulation_grid_version,
            baseline_generator_kind=source.baseline_generator_kind,
            baseline_generator_version=source.baseline_generator_version,
            transition_model_version=source.transition_model_version,
            minimum_coverage_required=source.minimum_coverage_required,
        )
        with self.assertRaisesRegex(ValueError, "complete grid"):
            calculate_robustness_region(incomplete)


if __name__ == "__main__":
    unittest.main()
