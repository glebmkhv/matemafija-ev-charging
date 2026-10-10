import unittest
from dataclasses import replace
from datetime import timedelta

from src.credit_simulation_grid import (
    CreditSimulationGridSpecification, run_credit_simulation_grid,
)
from src.fairness_safety import GuardStatus
from src.receiver_choice import FundedReceiverOffer
from src.simulation_contract import ProvenanceClass
from src.simulation_grid import (
    SimulationGridSpecification, run_paired_simulation_grid,
)
from tests.test_simulation_grid import (
    adoption, decisions, model, tariff, trajectory,
)


def upstream():
    baseline = trajectory()
    baseline = replace(
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
    return run_paired_simulation_grid(
        SimulationGridSpecification(
            price_intensity_values=(1,), theta_release_values=(0,),
            response_delay_minutes_values=(0,), replications=1,
            random_seed=7, theta_arrival_values=(20,),
        ),
        baseline, model(), decisions(), tariff(), adoption(),
        connector_key="connector-1", entity_id="evse-1",
    )


def inputs(result, *, amount=10, capacity=2):
    offers = {}
    capacities = {}
    for index, candidate in enumerate(result.runs[0].redistribution_candidates):
        receiver = f"receiver-{index % 2}"
        offers[candidate.candidate_id] = (FundedReceiverOffer(
            offer_id=f"offer-{index}", candidate_id=candidate.candidate_id,
            origin_site_id=candidate.origin_site_id,
            receiver_site_id=receiver, allocation_rank=1,
            amount_mcu=amount, distance_km=1+index/10,
            receiver_availability_ratio=.75,
            receiver_scarcity_ratio=.25,
            created_at_utc=candidate.evaluation_time_utc,
            expires_at_utc=candidate.evaluation_time_utc+timedelta(minutes=10),
            eligibility_decision_id=f"eligibility-{index}",
            allocation_batch_id="batch-1", allocation_contract_version="0.1",
            distance_provenance=ProvenanceClass.RECONSTRUCTED,
            receiver_state_provenance=ProvenanceClass.SIMULATED,
        ),)
        capacities[(receiver, candidate.evaluation_time_utc)] = capacity
    return offers, capacities


def grid(**changes):
    values = dict(
        beta_credit_per_mcu_values=(.1,),
        beta_distance_per_km_values=(.2,), reserve_ratio_values=(.1,),
        minimum_residual_receiver_capacity_values=(1,),
        opening_balance_mcu=100, choice_random_seed=31,
    )
    values.update(changes)
    return CreditSimulationGridSpecification(**values)


class CreditSimulationGridTest(unittest.TestCase):
    def test_grid_is_reproducible_and_reconciles_choice_ledger_and_safety(self):
        base = upstream()
        offers, capacities = inputs(base)
        first = run_credit_simulation_grid(base, grid(), offers, capacities)
        second = run_credit_simulation_grid(base, grid(), offers, capacities)
        self.assertEqual(first, second)
        run = first.runs[0]
        self.assertEqual(run.candidate_count, 3)
        self.assertEqual(run.proposed_offer_count, 3)
        self.assertEqual(run.safety_pass_offer_count, 3)
        self.assertEqual(run.selected_receiver_count, run.issuance_count)
        self.assertEqual(run.ledger_snapshot.reconciliation_difference_mcu, 0)
        self.assertTrue(run.common_random_numbers)

    def test_choice_draws_are_paired_across_credit_sensitivity(self):
        base = upstream()
        offers, capacities = inputs(base)
        result = run_credit_simulation_grid(
            base,
            grid(beta_credit_per_mcu_values=(0, .2)),
            offers, capacities,
        )
        self.assertEqual(len(result.runs), 2)
        first, second = result.runs
        self.assertEqual(
            [item.random_uniform for item in first.choice_outcomes],
            [item.random_uniform for item in second.choice_outcomes],
        )
        self.assertEqual(first.choice_random_seed, second.choice_random_seed)

    def test_unfundable_offers_are_blocked_before_choice(self):
        base = upstream()
        offers, capacities = inputs(base, amount=10)
        result = run_credit_simulation_grid(
            base,
            grid(reserve_ratio_values=(.95,)),
            offers, capacities,
        )
        run = result.runs[0]
        self.assertEqual(run.safety_block_offer_count, run.proposed_offer_count)
        self.assertEqual(run.selected_receiver_count, 0)
        self.assertTrue(all(
            "insufficient_offerable_mcu" in item.blocking_reasons
            for item in run.safety_decisions
        ))

    def test_residual_capacity_dimension_changes_safety_outcome(self):
        base = upstream()
        offers, capacities = inputs(base, capacity=1)
        result = run_credit_simulation_grid(
            base,
            grid(minimum_residual_receiver_capacity_values=(0, 1)),
            offers, capacities,
        )
        permissive, protected = result.runs
        self.assertEqual(permissive.safety_pass_offer_count, 3)
        self.assertEqual(protected.safety_block_offer_count, 3)
        self.assertEqual(
            protected.distributional_audit.status, GuardStatus.NOT_EVALUABLE,
        )

    def test_rejects_invalid_grid_axis(self):
        with self.assertRaisesRegex(ValueError, "reserve ratio"):
            grid(reserve_ratio_values=(1.1,)).validate()

    def test_rejects_offer_for_candidate_outside_upstream_grid(self):
        base = upstream()
        offers, capacities = inputs(base)
        sample = next(iter(offers.values()))[0]
        offers["unknown"] = (replace(sample, candidate_id="unknown"),)
        with self.assertRaisesRegex(ValueError, "outside the upstream grid"):
            run_credit_simulation_grid(base, grid(), offers, capacities)


if __name__ == "__main__":
    unittest.main()
