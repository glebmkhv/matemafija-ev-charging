import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from src.receiver_choice import (
    FundedReceiverOffer, ReceiverChoiceOutcomeType,
    ReceiverChoiceSpecification, draw_receiver_choice,
    evaluate_receiver_choice,
)
from src.simulation_contract import ProvenanceClass
from src.simulation_grid import RedistributionCandidate


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def candidate():
    return RedistributionCandidate(
        candidate_id="candidate-1", scenario_id="scenario-1",
        replication_index=0, origin_site_id="origin",
        origin_entity_id="evse-1", evaluation_time_utc=NOW,
        source_available_unit_index=0, paired_uniform=.15,
        baseline_start_probability=.2, adaptive_start_probability=.1,
    )


def offer(
    receiver, *, amount=10, distance=1, availability=.75, rank=1,
):
    return FundedReceiverOffer(
        offer_id=f"offer-{receiver}", candidate_id="candidate-1",
        origin_site_id="origin", receiver_site_id=receiver,
        allocation_rank=rank, amount_mcu=amount, distance_km=distance,
        receiver_availability_ratio=availability,
        receiver_scarcity_ratio=1-availability,
        created_at_utc=NOW, expires_at_utc=NOW+timedelta(minutes=10),
        eligibility_decision_id=f"eligibility-{receiver}",
        allocation_batch_id="batch-1", allocation_contract_version="0.1",
        distance_provenance=ProvenanceClass.RECONSTRUCTED,
        receiver_state_provenance=ProvenanceClass.SIMULATED,
    )


class ReceiverChoiceTest(unittest.TestCase):
    def test_empty_funded_choice_set_is_certain_outside(self):
        result = evaluate_receiver_choice(
            candidate(), (), ReceiverChoiceSpecification(.1, .5),
        )
        self.assertEqual(result.outside_probability, 1)
        self.assertEqual(result.alternatives, ())
        outcome = draw_receiver_choice(result, random_uniform=.25)
        self.assertEqual(outcome.outcome_type,
                         ReceiverChoiceOutcomeType.OUTSIDE_UNASSIGNED)
        self.assertFalse(outcome.reservation_required)

    def test_probabilities_sum_to_one_and_components_reconcile(self):
        result = evaluate_receiver_choice(
            candidate(),
            (offer("B", rank=1), offer("C", amount=15, distance=2, rank=2)),
            ReceiverChoiceSpecification(.1, .5),
        )
        self.assertAlmostEqual(result.probability_sum, 1)
        self.assertEqual(len(result.alternatives), 2)
        for row in result.alternatives:
            self.assertAlmostEqual(
                row.systematic_utility,
                row.credit_utility_component+row.distance_utility_component
                + row.availability_utility_component,
            )

    def test_more_credit_increases_own_probability(self):
        specification = ReceiverChoiceSpecification(.1, .5)
        low = evaluate_receiver_choice(
            candidate(), (offer("B", amount=5),), specification,
        )
        high = evaluate_receiver_choice(
            candidate(), (offer("B", amount=20),), specification,
        )
        self.assertGreater(high.alternatives[0].probability,
                           low.alternatives[0].probability)

    def test_more_distance_reduces_own_probability(self):
        specification = ReceiverChoiceSpecification(.1, .5)
        near = evaluate_receiver_choice(
            candidate(), (offer("B", distance=.5),), specification,
        )
        far = evaluate_receiver_choice(
            candidate(), (offer("B", distance=4),), specification,
        )
        self.assertLess(far.alternatives[0].probability,
                        near.alternatives[0].probability)

    def test_availability_effect_requires_visibility_assumption(self):
        with self.assertRaisesRegex(ValueError, "visibility"):
            ReceiverChoiceSpecification(.1, .5, beta_availability=1).validate()
        specification = ReceiverChoiceSpecification(
            .1, .5, beta_availability=1,
            receiver_availability_visible=True,
        )
        low = evaluate_receiver_choice(
            candidate(), (offer("B", availability=.5),), specification,
        )
        high = evaluate_receiver_choice(
            candidate(), (offer("B", availability=1),), specification,
        )
        self.assertGreater(high.alternatives[0].probability,
                           low.alternatives[0].probability)

    def test_draw_selects_offer_but_does_not_reserve_it(self):
        evaluation = evaluate_receiver_choice(
            candidate(), (offer("B"),), ReceiverChoiceSpecification(.2, .1),
        )
        selected = draw_receiver_choice(evaluation, random_uniform=0)
        self.assertEqual(selected.outcome_type,
                         ReceiverChoiceOutcomeType.RECEIVER_SELECTED)
        self.assertEqual(selected.selected_offer_id, "offer-B")
        self.assertTrue(selected.reservation_required)
        outside = draw_receiver_choice(evaluation, random_uniform=.999)
        self.assertEqual(outside.outcome_type,
                         ReceiverChoiceOutcomeType.OUTSIDE_UNASSIGNED)
        self.assertFalse(outside.reservation_required)

    def test_zero_coefficients_are_symmetric_and_large_utility_is_stable(self):
        symmetric = evaluate_receiver_choice(
            candidate(), (offer("B", rank=1), offer("C", rank=2)),
            ReceiverChoiceSpecification(0, 0),
        )
        self.assertAlmostEqual(symmetric.outside_probability, 1/3)
        self.assertTrue(all(
            abs(row.probability-1/3) < 1e-12
            for row in symmetric.alternatives
        ))
        extreme = evaluate_receiver_choice(
            candidate(), (offer("B", amount=25),),
            ReceiverChoiceSpecification(1_000, 0),
        )
        self.assertAlmostEqual(extreme.probability_sum, 1)
        self.assertTrue(all(
            __import__("math").isfinite(row.probability)
            for row in extreme.alternatives
        ))

    def test_rejects_foreign_expired_and_duplicate_offers(self):
        specification = ReceiverChoiceSpecification(.1, .5)
        with self.assertRaisesRegex(ValueError, "another candidate"):
            evaluate_receiver_choice(
                candidate(), (replace(offer("B"), candidate_id="other"),),
                specification,
            )
        with self.assertRaisesRegex(ValueError, "expiry"):
            evaluate_receiver_choice(
                candidate(), (replace(offer("B"), expires_at_utc=NOW),),
                specification,
            )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluate_receiver_choice(
                candidate(), (offer("B", rank=1), offer("B", rank=2)),
                specification,
            )

    def test_rejects_inconsistent_scarcity_and_too_many_offers(self):
        specification = ReceiverChoiceSpecification(.1, .5)
        with self.assertRaisesRegex(ValueError, "complement"):
            evaluate_receiver_choice(
                candidate(), (replace(
                    offer("B"), receiver_scarcity_ratio=.9,
                ),), specification,
            )
        with self.assertRaisesRegex(ValueError, "more than three"):
            evaluate_receiver_choice(
                candidate(), tuple(
                    offer(name, rank=index)
                    for index, name in enumerate(("B", "C", "D", "E"), 1)
                ), specification,
            )
        with self.assertRaisesRegex(ValueError, "5 km"):
            evaluate_receiver_choice(
                candidate(), (offer("B", distance=5.1),), specification,
            )


if __name__ == "__main__":
    unittest.main()
