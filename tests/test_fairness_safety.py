import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from src.fairness_safety import (
    FairnessSafetySpecification, GuardStatus,
    audit_distributional_proxies, evaluate_offer_safety,
)
from src.receiver_choice import (
    FundedReceiverOffer, ReceiverChoiceOutcome, ReceiverChoiceOutcomeType,
)
from src.simulation_contract import ProvenanceClass
from src.simulation_grid import RedistributionCandidate
from src.simulation_ledger import SimulationLedger


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def candidate(index=0):
    return RedistributionCandidate(
        candidate_id=f"candidate-{index}", scenario_id="scenario-1",
        replication_index=0, origin_site_id="origin",
        origin_entity_id=f"evse-{index}", evaluation_time_utc=NOW,
        source_available_unit_index=index, paired_uniform=.15,
        baseline_start_probability=.2, adaptive_start_probability=.1,
    )


def offer(item, receiver="receiver-a", *, amount=10, distance=1):
    return FundedReceiverOffer(
        offer_id=f"offer-{item.candidate_id}", candidate_id=item.candidate_id,
        origin_site_id=item.origin_site_id, receiver_site_id=receiver,
        allocation_rank=1, amount_mcu=amount, distance_km=distance,
        receiver_availability_ratio=.75, receiver_scarcity_ratio=.25,
        created_at_utc=NOW, expires_at_utc=NOW+timedelta(minutes=10),
        eligibility_decision_id=f"eligibility-{item.candidate_id}",
        allocation_batch_id="batch-1", allocation_contract_version="0.1",
        distance_provenance=ProvenanceClass.RECONSTRUCTED,
        receiver_state_provenance=ProvenanceClass.SIMULATED,
    )


def ledger(*, opening=100, receiver="receiver-a", capacity=2):
    book = SimulationLedger(
        scenario_id="scenario-1", replication_index=0,
        policy_id="credit-policy", policy_version="1",
        trajectory_id="trajectory-1", random_seed=7,
        opening_balance_mcu=opening, opened_at_utc=NOW,
    )
    book.open_receiver_capacity(receiver, capacity, at=NOW)
    return book


def outside_outcome(item):
    return ReceiverChoiceOutcome(
        candidate_id=item.candidate_id, scenario_id=item.scenario_id,
        replication_index=0, evaluation_time_utc=NOW, random_uniform=.9,
        outcome_type=ReceiverChoiceOutcomeType.OUTSIDE_UNASSIGNED,
        selected_offer_id=None, selected_receiver_site_id=None,
        selected_amount_mcu=None, reservation_required=False,
        model_id="choice", model_version="1",
    )


def safety(item, funded_offer):
    return evaluate_offer_safety(
        item, funded_offer,
        ledger(receiver=funded_offer.receiver_site_id).snapshot,
        FairnessSafetySpecification(), evaluation_time_utc=NOW,
    )


class FairnessSafetyTest(unittest.TestCase):
    def test_offer_passes_observable_guards_but_keeps_limitations(self):
        item = candidate()
        decision = evaluate_offer_safety(
            item, offer(item), ledger().snapshot,
            FairnessSafetySpecification(), evaluation_time_utc=NOW,
        )
        self.assertEqual(decision.status, GuardStatus.PASS)
        self.assertTrue(decision.reservation_allowed)
        self.assertEqual(decision.receiver_available_after, 1)
        self.assertIn("demographic_fairness_not_evaluable", decision.warnings)
        self.assertFalse(decision.personalized_recommendation_allowed)

    def test_residual_capacity_guard_prevents_scarcity_transfer(self):
        item = candidate()
        decision = evaluate_offer_safety(
            item, offer(item), ledger(capacity=1).snapshot,
            FairnessSafetySpecification(), evaluation_time_utc=NOW,
        )
        self.assertEqual(decision.status, GuardStatus.BLOCK)
        self.assertIn(
            "minimum_residual_receiver_capacity_violated",
            decision.blocking_reasons,
        )

    def test_expiry_and_fundability_are_hard_blocks(self):
        item = candidate()
        decision = evaluate_offer_safety(
            item, offer(item, amount=25), ledger(opening=20).snapshot,
            FairnessSafetySpecification(),
            evaluation_time_utc=NOW+timedelta(minutes=10),
        )
        self.assertIn("offer_expired", decision.blocking_reasons)
        self.assertIn("insufficient_offerable_mcu", decision.blocking_reasons)

    def test_small_batch_is_not_evaluable_not_fair(self):
        item = candidate()
        report = audit_distributional_proxies(
            total_candidate_count=1, offers=(offer(item),),
            outcomes=(outside_outcome(item),), safety_decisions=(),
            specification=FairnessSafetySpecification(),
        )
        self.assertEqual(report.status, GuardStatus.NOT_EVALUABLE)
        self.assertIn(
            "candidate_sample_below_distributional_minimum",
            report.limitations,
        )
        self.assertFalse(report.demographic_fairness_evaluable)

    def test_no_offer_exclusion_blocks_adequate_batch(self):
        rows = tuple(offer(candidate(index)) for index in range(5))
        decisions = tuple(
            safety(candidate(index), row) for index, row in enumerate(rows)
        )
        report = audit_distributional_proxies(
            total_candidate_count=20, offers=rows, outcomes=(),
            safety_decisions=decisions,
            specification=FairnessSafetySpecification(),
        )
        self.assertEqual(report.status, GuardStatus.BLOCK)
        self.assertEqual(report.no_offer_share, .75)
        self.assertIn("no_offer_share_exceeds_guard", report.blocking_reasons)

    def test_receiver_concentration_blocks_distributional_audit(self):
        rows = tuple(offer(candidate(index)) for index in range(20))
        decisions = tuple(
            safety(candidate(index), row) for index, row in enumerate(rows)
        )
        report = audit_distributional_proxies(
            total_candidate_count=20, offers=rows, outcomes=(),
            safety_decisions=decisions,
            specification=FairnessSafetySpecification(),
        )
        self.assertEqual(report.status, GuardStatus.BLOCK)
        self.assertIn(
            "receiver_offer_concentration_exceeds_guard",
            report.blocking_reasons,
        )

    def test_balanced_observable_proxies_can_pass_without_demographic_claim(self):
        rows = tuple(
            offer(candidate(index), receiver=f"receiver-{index % 2}")
            for index in range(20)
        )
        decisions = tuple(
            safety(candidate(index), row) for index, row in enumerate(rows)
        )
        report = audit_distributional_proxies(
            total_candidate_count=20, offers=rows, outcomes=(),
            safety_decisions=decisions,
            specification=FairnessSafetySpecification(),
        )
        self.assertEqual(report.status, GuardStatus.PASS)
        self.assertEqual(report.maximum_receiver_offer_count_share, .5)
        self.assertFalse(report.demographic_fairness_evaluable)

    def test_policy_thresholds_are_validated(self):
        with self.assertRaisesRegex(ValueError, "ratios"):
            replace(
                FairnessSafetySpecification(), maximum_no_offer_share=1.1,
            ).validate()


if __name__ == "__main__":
    unittest.main()
