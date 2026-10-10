import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from src.receiver_choice import (
    FundedReceiverOffer, ReceiverChoiceOutcome, ReceiverChoiceOutcomeType,
    ReceiverChoiceSpecification, draw_receiver_choice, evaluate_receiver_choice,
)
from src.simulation_contract import ProvenanceClass
from src.simulation_grid import RedistributionCandidate
from src.simulation_ledger import (
    LedgerEventType, SimulationLedger, replay_simulation_ledger,
)


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def candidate(name="1", unit_index=0):
    return RedistributionCandidate(
        candidate_id=f"candidate-{name}", scenario_id="scenario-1",
        replication_index=0, origin_site_id="origin",
        origin_entity_id="evse-1", evaluation_time_utc=NOW,
        source_available_unit_index=unit_index, paired_uniform=.15,
        baseline_start_probability=.2, adaptive_start_probability=.1,
    )


def offer(item, receiver="receiver", amount=25):
    return FundedReceiverOffer(
        offer_id=f"offer-{item.candidate_id}", candidate_id=item.candidate_id,
        origin_site_id="origin", receiver_site_id=receiver,
        allocation_rank=1, amount_mcu=amount, distance_km=1,
        receiver_availability_ratio=.75, receiver_scarcity_ratio=.25,
        created_at_utc=NOW, expires_at_utc=NOW+timedelta(minutes=10),
        eligibility_decision_id=f"eligibility-{item.candidate_id}",
        allocation_batch_id="batch-1", allocation_contract_version="0.1",
        distance_provenance=ProvenanceClass.RECONSTRUCTED,
        receiver_state_provenance=ProvenanceClass.SIMULATED,
    )


def selected_outcome(item, funded_offer):
    evaluation = evaluate_receiver_choice(
        item, (funded_offer,), ReceiverChoiceSpecification(1, 0),
    )
    return draw_receiver_choice(evaluation, random_uniform=0)


def ledger(opening=100):
    return SimulationLedger(
        scenario_id="scenario-1", replication_index=0,
        policy_id="credit-policy", policy_version="1",
        trajectory_id="trajectory-1", random_seed=7,
        opening_balance_mcu=opening, opened_at_utc=NOW,
    )


class SimulationLedgerTest(unittest.TestCase):
    def test_atomic_reservation_moves_mcu_and_capacity_together(self):
        item = candidate()
        funded_offer = offer(item)
        book = ledger()
        book.open_receiver_capacity("receiver", 1, at=NOW)
        book.register_offer(funded_offer)
        attempt = book.record_choice(selected_outcome(item, funded_offer), funded_offer)
        self.assertTrue(attempt.success)
        state = book.snapshot
        self.assertEqual(state.available_mcu, 75)
        self.assertEqual(state.reserved_mcu, 25)
        self.assertEqual(state.offerable_mcu, 65)
        self.assertEqual(state.receiver_available[0][2], 0)
        self.assertEqual(state.receiver_reserved[0][2], 1)
        self.assertEqual(dict(state.offer_statuses)[funded_offer.offer_id], "reserved")
        self.assertEqual(dict(state.reservation_statuses)[attempt.reservation_id], "active")

    def test_insufficient_pool_fails_without_partial_reservation(self):
        item = candidate()
        funded_offer = offer(item)
        book = ledger(opening=20)
        book.open_receiver_capacity("receiver", 1, at=NOW)
        book.register_offer(funded_offer)
        before = book.snapshot
        attempt = book.record_choice(selected_outcome(item, funded_offer), funded_offer)
        self.assertFalse(attempt.success)
        self.assertEqual(attempt.reason_code, "insufficient_offerable_mcu")
        state = book.snapshot
        self.assertEqual(state.available_mcu, before.available_mcu)
        self.assertEqual(state.reserved_mcu, 0)
        self.assertEqual(state.receiver_available[0][2], 1)
        self.assertEqual(state.receiver_reserved[0][2], 0)
        self.assertEqual(dict(state.offer_statuses)[funded_offer.offer_id],
                         "selection_failed")

    def test_competing_choices_cannot_overbook_one_receiver(self):
        first, second = candidate("1", 0), candidate("2", 1)
        first_offer, second_offer = offer(first), offer(second)
        book = ledger(opening=100)
        book.open_receiver_capacity("receiver", 1, at=NOW)
        book.register_offer(first_offer)
        book.register_offer(second_offer)
        accepted = book.record_choice(selected_outcome(first, first_offer), first_offer)
        rejected = book.record_choice(selected_outcome(second, second_offer), second_offer)
        self.assertTrue(accepted.success)
        self.assertFalse(rejected.success)
        self.assertEqual(rejected.reason_code, "receiver_capacity_unavailable")
        self.assertEqual(book.snapshot.receiver_reserved[0][2], 1)
        self.assertEqual(book.snapshot.reserved_mcu, 25)

    def test_completion_issues_credit_only_after_receiver_start(self):
        item = candidate()
        funded_offer = offer(item)
        book = ledger()
        book.open_receiver_capacity("receiver", 1, at=NOW)
        book.register_offer(funded_offer)
        attempt = book.record_choice(selected_outcome(item, funded_offer), funded_offer)
        issuance = book.complete_receiver_start(
            attempt.reservation_id, at=NOW+timedelta(minutes=1),
        )
        state = book.snapshot
        self.assertEqual(state.reserved_mcu, 0)
        self.assertEqual(state.outstanding_mcu, 25)
        self.assertEqual(state.receiver_reserved[0][2], 0)
        self.assertEqual(state.receiver_consumed[0][2], 1)
        event_types = [event.event_type for event in book.events]
        self.assertLess(event_types.index(LedgerEventType.SIMULATED_RECEIVER_START),
                        event_types.index(LedgerEventType.CREDIT_ISSUED))
        self.assertEqual(dict(state.issuance_remaining)[issuance.issuance_id], 25)

    def test_partial_and_full_redemption_preserve_funding_identity(self):
        item = candidate()
        funded_offer = offer(item)
        book = ledger()
        book.open_receiver_capacity("receiver", 1, at=NOW)
        book.register_offer(funded_offer)
        attempt = book.record_choice(selected_outcome(item, funded_offer), funded_offer)
        issuance = book.complete_receiver_start(
            attempt.reservation_id, at=NOW+timedelta(minutes=1),
        )
        partial = book.redeem(
            issuance.issuance_id, 10, at=NOW+timedelta(minutes=2),
        )
        self.assertEqual(partial.event_type, LedgerEventType.CREDIT_PARTIALLY_REDEEMED)
        final = book.redeem(
            issuance.issuance_id, 15, at=NOW+timedelta(minutes=3),
        )
        self.assertEqual(final.event_type, LedgerEventType.CREDIT_FULLY_REDEEMED)
        state = book.snapshot
        self.assertEqual(state.outstanding_mcu, 0)
        self.assertEqual(state.settled_mcu, 25)
        self.assertEqual(state.reconciliation_difference_mcu, 0)

    def test_expiry_returns_only_remaining_issuance_to_available(self):
        item = candidate()
        funded_offer = offer(item)
        book = ledger()
        book.open_receiver_capacity("receiver", 1, at=NOW)
        book.register_offer(funded_offer)
        attempt = book.record_choice(selected_outcome(item, funded_offer), funded_offer)
        issuance = book.complete_receiver_start(
            attempt.reservation_id, at=NOW+timedelta(minutes=1),
        )
        book.redeem(issuance.issuance_id, 10, at=NOW+timedelta(minutes=2))
        expired = book.close_outstanding_credit(
            issuance.issuance_id, at=NOW+timedelta(days=31),
            outcome="expired", reason_code="credit_validity_elapsed",
        )
        self.assertEqual(expired.event_type, LedgerEventType.CREDIT_EXPIRED)
        state = book.snapshot
        self.assertEqual(state.available_mcu, 90)
        self.assertEqual(state.outstanding_mcu, 0)
        self.assertEqual(state.settled_mcu, 10)
        self.assertEqual(dict(state.issuance_remaining)[issuance.issuance_id], 0)

    def test_release_restores_both_capacity_and_credit(self):
        item = candidate()
        funded_offer = offer(item)
        book = ledger()
        book.open_receiver_capacity("receiver", 1, at=NOW)
        book.register_offer(funded_offer)
        attempt = book.record_choice(selected_outcome(item, funded_offer), funded_offer)
        book.release_reservation(
            attempt.reservation_id, at=NOW+timedelta(minutes=1),
            reason_code="receiver_start_failed",
        )
        state = book.snapshot
        self.assertEqual(state.available_mcu, 100)
        self.assertEqual(state.reserved_mcu, 0)
        self.assertEqual(state.receiver_available[0][2], 1)
        self.assertEqual(state.receiver_reserved[0][2], 0)
        self.assertEqual(dict(state.reservation_statuses)[attempt.reservation_id],
                         "released")

    def test_replay_is_deterministic_and_tampering_is_rejected(self):
        book = ledger()
        original = book.events
        book.accrue_contribution(
            5, at=NOW+timedelta(minutes=1), correlation_id="origin-service-1",
            reason_code="simulated_origin_service_completed",
        )
        self.assertEqual(len(original), 1)
        replayed = replay_simulation_ledger(
            book.events, reserve_ratio=book.reserve_ratio,
        )
        self.assertEqual(replayed, book.snapshot)
        tampered = list(book.events)
        tampered[1] = replace(tampered[1], sequence_number=99)
        with self.assertRaisesRegex(ValueError, "contiguous"):
            replay_simulation_ledger(tampered, reserve_ratio=book.reserve_ratio)

    def test_candidate_cannot_receive_two_terminal_choice_outcomes(self):
        item = candidate()
        book = ledger()
        outside = ReceiverChoiceOutcome(
            candidate_id=item.candidate_id, scenario_id=item.scenario_id,
            replication_index=item.replication_index,
            evaluation_time_utc=NOW, random_uniform=.9,
            outcome_type=ReceiverChoiceOutcomeType.OUTSIDE_UNASSIGNED,
            selected_offer_id=None, selected_receiver_site_id=None,
            selected_amount_mcu=None, reservation_required=False,
            model_id="choice", model_version="1",
        )
        book.record_choice(outside)
        with self.assertRaisesRegex(ValueError, "already has a choice outcome"):
            book.record_choice(outside)


if __name__ == "__main__":
    unittest.main()
