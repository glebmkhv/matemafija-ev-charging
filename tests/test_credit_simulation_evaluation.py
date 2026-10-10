import unittest
from dataclasses import replace

from src.credit_simulation_evaluation import (
    MetricAvailability, evaluate_credit_simulation_grid,
)
from src.credit_simulation_grid import run_credit_simulation_grid
from src.simulation_evaluation import evaluate_simulation_grid_scarcity
from src.simulation_grid import (
    SimulationGridSpecification, run_paired_simulation_grid,
)
from tests.test_credit_simulation_grid import grid, inputs, upstream
from tests.test_simulation_grid import (
    adoption, decisions, model, tariff, trajectory,
)


def available_trajectory():
    baseline = trajectory()
    return replace(
        baseline,
        points=tuple(replace(
            point,
            source_state=replace(
                point.source_state,
                available_evse_count=4, charging_evse_count=0,
                availability_ratio=1, occupancy_proxy=0,
                zero_availability_evidence=False,
            ),
        ) for point in baseline.points),
    )


class CreditSimulationEvaluationTest(unittest.TestCase):
    def test_four_domains_reconcile_for_every_downstream_run(self):
        base = upstream()
        offers, capacities = inputs(base)
        credit = run_credit_simulation_grid(base, grid(), offers, capacities)
        scarcity = evaluate_simulation_grid_scarcity(base, available_trajectory())
        result = evaluate_credit_simulation_grid(credit, scarcity)
        self.assertEqual(len(result.evaluations), 1)
        item = result.evaluations[0]
        self.assertEqual(
            item.system.scarcity_metric_availability,
            MetricAvailability.AVAILABLE,
        )
        self.assertEqual(item.redistribution.candidate_count, 3)
        self.assertEqual(
            item.redistribution.selected_receiver_count,
            item.accounting.issuance_count,
        )
        self.assertEqual(
            item.user_proxy.selected_offer_count,
            item.redistribution.selected_receiver_count,
        )
        self.assertTrue(item.accounting.solvent_and_reconciled)
        self.assertEqual(item.accounting.reconciliation_difference_mcu, 0)

    def test_unavailable_user_outcomes_remain_not_evaluable(self):
        base = upstream()
        offers, capacities = inputs(base)
        credit = run_credit_simulation_grid(base, grid(), offers, capacities)
        scarcity = evaluate_simulation_grid_scarcity(base, available_trajectory())
        item = evaluate_credit_simulation_grid(credit, scarcity).evaluations[0]
        self.assertEqual(
            item.user_proxy.total_session_cost_availability,
            MetricAvailability.NOT_EVALUABLE,
        )
        self.assertEqual(
            item.user_proxy.travel_time_availability,
            MetricAvailability.NOT_EVALUABLE,
        )
        self.assertEqual(
            item.user_proxy.welfare_availability,
            MetricAvailability.NOT_EVALUABLE,
        )
        self.assertEqual(
            item.user_proxy.demographic_fairness_availability,
            MetricAvailability.NOT_EVALUABLE,
        )

    def test_zero_candidate_run_uses_absent_shares_not_false_zero_effect(self):
        baseline = available_trajectory()
        base = run_paired_simulation_grid(
            SimulationGridSpecification(
                price_intensity_values=(1,), theta_release_values=(0,),
                response_delay_minutes_values=(0,), replications=1,
                random_seed=7, theta_arrival_values=(0,),
            ),
            baseline, model(), decisions(), tariff(), adoption(),
            connector_key="connector-1", entity_id="evse-1",
        )
        credit = run_credit_simulation_grid(base, grid(), {}, {})
        scarcity = evaluate_simulation_grid_scarcity(base, baseline)
        item = evaluate_credit_simulation_grid(credit, scarcity).evaluations[0]
        self.assertEqual(item.redistribution.candidate_count, 0)
        self.assertIsNone(item.redistribution.realized_redistribution_share)
        self.assertIsNone(item.redistribution.outside_unassigned_share)
        self.assertIsNone(item.user_proxy.mean_proposed_credit_mcu)
        self.assertIsNone(item.accounting.redemption_rate)

    def test_rejects_downstream_candidate_mismatch(self):
        base = upstream()
        offers, capacities = inputs(base)
        credit = run_credit_simulation_grid(base, grid(), offers, capacities)
        bad_run = replace(credit.runs[0], candidate_count=2)
        bad_credit = replace(credit, runs=(bad_run,))
        scarcity = evaluate_simulation_grid_scarcity(base, available_trajectory())
        with self.assertRaises(ValueError):
            evaluate_credit_simulation_grid(bad_credit, scarcity)


if __name__ == "__main__":
    unittest.main()
