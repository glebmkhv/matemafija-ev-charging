"""Append-only event ledger for simulated MCU and receiver-capacity lifecycles."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math

try:
    from .receiver_choice import (
        FundedReceiverOffer, ReceiverChoiceOutcome, ReceiverChoiceOutcomeType,
    )
    from .simulation_contract import ClaimScope, ExecutionMode, ProvenanceClass
except ImportError:  # pragma: no cover
    from receiver_choice import (
        FundedReceiverOffer, ReceiverChoiceOutcome, ReceiverChoiceOutcomeType,
    )
    from simulation_contract import ClaimScope, ExecutionMode, ProvenanceClass


LEDGER_VERSION = "1.0.0"
UNIT_CONTRACT_VERSION = "0.1"


class LedgerEventType(str, Enum):
    OPENING_BALANCE_FUNDED = "opening_balance_funded"
    EXTERNAL_SUBSIDY_FUNDED = "external_subsidy_funded"
    CONTRIBUTION_ACCRUED = "contribution_accrued"
    CONTRIBUTION_REVERSED = "contribution_reversed"
    RECEIVER_CAPACITY_OPENED = "receiver_capacity_opened"
    CREDIT_OFFER_CREATED = "credit_offer_created"
    CREDIT_OFFER_DECLINED = "credit_offer_declined"
    CREDIT_OFFER_EXPIRED = "credit_offer_expired"
    CREDIT_OFFER_WITHDRAWN = "credit_offer_withdrawn"
    CANDIDATE_UNASSIGNED = "candidate_unassigned"
    ALTERNATIVE_SELECTED = "alternative_selected"
    RECEIVER_CAPACITY_RESERVED = "receiver_capacity_reserved"
    CREDIT_RESERVED = "credit_reserved"
    RECEIVER_CAPACITY_RELEASED = "receiver_capacity_released"
    CREDIT_RESERVATION_RELEASED = "credit_reservation_released"
    SELECTION_FAILED = "selection_failed"
    SIMULATED_RECEIVER_START = "simulated_receiver_start"
    CREDIT_ISSUED = "credit_issued"
    CREDIT_PARTIALLY_REDEEMED = "credit_partially_redeemed"
    CREDIT_FULLY_REDEEMED = "credit_fully_redeemed"
    CREDIT_EXPIRED = "credit_expired"
    CREDIT_REVERSED = "credit_reversed"


@dataclass(frozen=True)
class SimulationLedgerEvent:
    event_id: str
    sequence_number: int
    event_type: LedgerEventType
    event_time_utc: datetime
    scenario_id: str
    replication_index: int
    correlation_id: str
    causation_event_id: str | None
    policy_id: str
    policy_version: str
    reason_code: str | None = None
    amount_mcu: int | None = None
    capacity_units: int | None = None
    offer_id: str | None = None
    reservation_id: str | None = None
    issuance_id: str | None = None
    origin_site_id: str | None = None
    receiver_site_id: str | None = None
    expires_at_utc: datetime | None = None
    trajectory_id: str | None = None
    random_seed: int | None = None
    execution_mode: ExecutionMode = ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL
    claim_scope: ClaimScope = ClaimScope.SCENARIO_CONDITIONAL
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    event_version: str = LEDGER_VERSION
    unit_contract_version: str = UNIT_CONTRACT_VERSION

    def validate(self):
        if not all((self.event_id, self.correlation_id, self.policy_id,
                    self.policy_version, self.event_version)):
            raise ValueError("Ledger event envelope is incomplete")
        if not isinstance(self.event_type, LedgerEventType):
            raise ValueError("Ledger event type is invalid")
        if (isinstance(self.sequence_number, bool)
                or not isinstance(self.sequence_number, int)
                or self.sequence_number < 0
                or isinstance(self.replication_index, bool)
                or not isinstance(self.replication_index, int)
                or self.replication_index < 0):
            raise ValueError("Ledger event sequence and replication must be non-negative")
        if self.event_time_utc.tzinfo is None:
            raise ValueError("Ledger event timestamp must include a timezone")
        if self.expires_at_utc is not None:
            if self.expires_at_utc.tzinfo is None:
                raise ValueError("Ledger expiry timestamp must include a timezone")
            if self.expires_at_utc <= self.event_time_utc:
                raise ValueError("Ledger expiry must follow the event")
        for name, value in (
            ("amount_mcu", self.amount_mcu),
            ("capacity_units", self.capacity_units),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"Ledger {name} must be a positive integer")
        if (self.random_seed is not None
                and (isinstance(self.random_seed, bool)
                     or not isinstance(self.random_seed, int)
                     or self.random_seed < 0)):
            raise ValueError("Ledger random seed must be non-negative")
        if self.execution_mode is not ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL:
            raise ValueError("Credit ledger is only valid in assumption-driven mode")
        if self.claim_scope is not ClaimScope.SCENARIO_CONDITIONAL:
            raise ValueError("Credit ledger events must remain scenario-conditional")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Credit ledger events must be simulated")


@dataclass(frozen=True)
class SimulationLedgerSnapshot:
    funded_mcu: int
    available_mcu: int
    reserved_mcu: int
    outstanding_mcu: int
    settled_mcu: int
    reserve_target_mcu: int
    offerable_mcu: int
    receiver_available: tuple[tuple[str, datetime, int], ...]
    receiver_reserved: tuple[tuple[str, datetime, int], ...]
    receiver_consumed: tuple[tuple[str, datetime, int], ...]
    offer_statuses: tuple[tuple[str, str], ...]
    candidate_statuses: tuple[tuple[str, str], ...]
    reservation_statuses: tuple[tuple[str, str], ...]
    issuance_remaining: tuple[tuple[str, int], ...]
    reconciliation_difference_mcu: int
    event_count: int

    def validate(self):
        balances = (
            self.funded_mcu, self.available_mcu, self.reserved_mcu,
            self.outstanding_mcu, self.settled_mcu,
            self.reserve_target_mcu, self.offerable_mcu,
        )
        if any(value < 0 for value in balances):
            raise ValueError("Ledger balances cannot be negative")
        expected = (
            self.funded_mcu-self.available_mcu-self.reserved_mcu
            -self.outstanding_mcu-self.settled_mcu
        )
        if self.reconciliation_difference_mcu != expected or expected != 0:
            raise ValueError("Ledger funding identity does not reconcile")
        if self.offerable_mcu != max(0, self.available_mcu-self.reserve_target_mcu):
            raise ValueError("Ledger offerable balance is inconsistent")
        for rows in (
            self.receiver_available, self.receiver_reserved,
            self.receiver_consumed,
        ):
            if any(value < 0 for _, _, value in rows):
                raise ValueError("Receiver-capacity balances cannot be negative")


@dataclass(frozen=True)
class ReservationAttempt:
    success: bool
    reason_code: str
    reservation_id: str | None
    selection_event_id: str


class SimulationLedger:
    """In-memory append-only log; state is always rebuilt from its events."""

    def __init__(
        self,
        *,
        scenario_id: str,
        replication_index: int,
        policy_id: str,
        policy_version: str,
        trajectory_id: str,
        random_seed: int,
        reserve_ratio: float = 0.10,
        opening_balance_mcu: int = 0,
        external_subsidy_mcu: int = 0,
        opened_at_utc: datetime,
    ):
        if not all((scenario_id, policy_id, policy_version, trajectory_id)):
            raise ValueError("Ledger identity is incomplete")
        if opened_at_utc.tzinfo is None:
            raise ValueError("Ledger opening time must include a timezone")
        if (isinstance(replication_index, bool) or not isinstance(replication_index, int)
                or replication_index < 0 or isinstance(random_seed, bool)
                or not isinstance(random_seed, int) or random_seed < 0):
            raise ValueError("Ledger replication and seed must be non-negative integers")
        if (isinstance(reserve_ratio, bool)
                or not isinstance(reserve_ratio, (int, float))
                or not math.isfinite(reserve_ratio) or not 0 <= reserve_ratio <= 1):
            raise ValueError("Ledger reserve ratio must be in [0, 1]")
        for value in (opening_balance_mcu, external_subsidy_mcu):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Ledger opening funding must be non-negative integer MCU")
        self.scenario_id = scenario_id
        self.replication_index = replication_index
        self.policy_id = policy_id
        self.policy_version = policy_version
        self.trajectory_id = trajectory_id
        self.random_seed = random_seed
        self.reserve_ratio = float(reserve_ratio)
        self._events: list[SimulationLedgerEvent] = []
        if opening_balance_mcu:
            self._append_batch((self._event(
                LedgerEventType.OPENING_BALANCE_FUNDED,
                opened_at_utc,
                correlation_id="ledger-opening",
                amount_mcu=opening_balance_mcu,
            ),))
        if external_subsidy_mcu:
            self._append_batch((self._event(
                LedgerEventType.EXTERNAL_SUBSIDY_FUNDED,
                opened_at_utc,
                correlation_id="ledger-subsidy",
                amount_mcu=external_subsidy_mcu,
            ),))

    @property
    def events(self):
        return tuple(self._events)

    @property
    def snapshot(self):
        return replay_simulation_ledger(self.events, reserve_ratio=self.reserve_ratio)

    def _event(
        self, event_type, at, *, correlation_id, causation_event_id=None,
        sequence_offset=0, **kwargs,
    ):
        sequence = len(self._events)+sequence_offset
        return SimulationLedgerEvent(
            event_id=(
                f"ledger:{self.scenario_id}:{self.replication_index}:"
                f"{sequence}:{event_type.value}"
            ),
            sequence_number=sequence,
            event_type=event_type,
            event_time_utc=at,
            scenario_id=self.scenario_id,
            replication_index=self.replication_index,
            correlation_id=correlation_id,
            causation_event_id=causation_event_id,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            trajectory_id=self.trajectory_id,
            random_seed=self.random_seed,
            **kwargs,
        )

    def _append_batch(self, events):
        rows = tuple(events)
        if not rows:
            return
        expected_sequence = len(self._events)
        previous_time = self._events[-1].event_time_utc if self._events else None
        prior_ids = {item.event_id for item in self._events}
        batch_ids = set()
        for offset, event in enumerate(rows):
            event.validate()
            if event.sequence_number != expected_sequence+offset:
                raise ValueError("Ledger batch sequence is not contiguous")
            if (event.scenario_id != self.scenario_id
                    or event.replication_index != self.replication_index):
                raise ValueError("Ledger event belongs to another scenario wallet")
            if previous_time is not None and event.event_time_utc < previous_time:
                raise ValueError("Ledger event time cannot move backwards")
            if event.event_id in prior_ids or event.event_id in batch_ids:
                raise ValueError("Ledger event IDs must be unique")
            if (event.causation_event_id is not None
                    and event.causation_event_id not in prior_ids | batch_ids):
                raise ValueError("Ledger causation must reference an earlier event")
            batch_ids.add(event.event_id)
            previous_time = event.event_time_utc
        # Validate the complete prospective log before mutating the append-only list.
        replay_simulation_ledger(
            self.events+rows, reserve_ratio=self.reserve_ratio,
        )
        self._events.extend(rows)

    def accrue_contribution(self, amount_mcu, *, at, correlation_id, reason_code):
        event = self._event(
            LedgerEventType.CONTRIBUTION_ACCRUED, at,
            correlation_id=correlation_id, amount_mcu=amount_mcu,
            reason_code=reason_code,
        )
        self._append_batch((event,))
        return event

    def open_receiver_capacity(self, receiver_site_id, capacity_units, *, at):
        event = self._event(
            LedgerEventType.RECEIVER_CAPACITY_OPENED, at,
            correlation_id=f"capacity:{receiver_site_id}:{at.isoformat()}",
            receiver_site_id=receiver_site_id,
            capacity_units=capacity_units,
        )
        self._append_batch((event,))
        return event

    def register_offer(self, offer: FundedReceiverOffer):
        event = self._event(
            LedgerEventType.CREDIT_OFFER_CREATED,
            offer.created_at_utc,
            correlation_id=offer.candidate_id,
            amount_mcu=offer.amount_mcu,
            offer_id=offer.offer_id,
            origin_site_id=offer.origin_site_id,
            receiver_site_id=offer.receiver_site_id,
            expires_at_utc=offer.expires_at_utc,
        )
        self._append_batch((event,))
        return event

    def terminate_unselected_offer(self, offer_id, *, at, outcome, reason_code):
        event_types = {
            "declined": LedgerEventType.CREDIT_OFFER_DECLINED,
            "expired": LedgerEventType.CREDIT_OFFER_EXPIRED,
            "withdrawn": LedgerEventType.CREDIT_OFFER_WITHDRAWN,
        }
        if outcome not in event_types:
            raise ValueError("Unsupported unselected-offer terminal outcome")
        created = next((
            event for event in reversed(self.events)
            if event.event_type is LedgerEventType.CREDIT_OFFER_CREATED
            and event.offer_id == offer_id
        ), None)
        if created is None or dict(self.snapshot.offer_statuses).get(offer_id) != "created":
            raise ValueError("Offer termination requires a live created offer")
        if (outcome == "expired"
                and created.expires_at_utc is not None
                and at < created.expires_at_utc):
            raise ValueError("Offer cannot expire before its validity deadline")
        event = self._event(
            event_types[outcome], at,
            correlation_id=created.correlation_id,
            causation_event_id=created.event_id,
            offer_id=offer_id,
            receiver_site_id=created.receiver_site_id,
            amount_mcu=created.amount_mcu,
            reason_code=reason_code,
        )
        self._append_batch((event,))
        return event

    def record_choice(self, outcome: ReceiverChoiceOutcome, offer: FundedReceiverOffer | None = None):
        outcome.validate()
        if (outcome.scenario_id != self.scenario_id
                or outcome.replication_index != self.replication_index):
            raise ValueError("Choice outcome belongs to another ledger")
        if outcome.outcome_type is ReceiverChoiceOutcomeType.OUTSIDE_UNASSIGNED:
            event = self._event(
                LedgerEventType.CANDIDATE_UNASSIGNED,
                outcome.evaluation_time_utc,
                correlation_id=outcome.candidate_id,
                reason_code="outside_option_selected",
            )
            self._append_batch((event,))
            return ReservationAttempt(False, "outside_option_selected", None, event.event_id)
        if offer is None:
            raise ValueError("Selected receiver outcome requires its funded offer")
        if (offer.offer_id != outcome.selected_offer_id
                or offer.receiver_site_id != outcome.selected_receiver_site_id
                or offer.amount_mcu != outcome.selected_amount_mcu
                or offer.candidate_id != outcome.candidate_id):
            raise ValueError("Selected outcome and funded offer are inconsistent")

        snapshot = self.snapshot
        offer_status = dict(snapshot.offer_statuses).get(offer.offer_id)
        if offer_status != "created":
            raise ValueError("Selected offer is not live in this ledger")
        selection = self._event(
            LedgerEventType.ALTERNATIVE_SELECTED,
            outcome.evaluation_time_utc,
            correlation_id=outcome.candidate_id,
            offer_id=offer.offer_id,
            origin_site_id=offer.origin_site_id,
            receiver_site_id=offer.receiver_site_id,
            amount_mcu=offer.amount_mcu,
        )
        reason = None
        if outcome.evaluation_time_utc >= offer.expires_at_utc:
            reason = "offer_expired_before_reservation"
        elif snapshot.offerable_mcu < offer.amount_mcu:
            reason = "insufficient_offerable_mcu"
        else:
            capacity = {
                (site, at): value for site, at, value in snapshot.receiver_available
            }.get((offer.receiver_site_id, outcome.evaluation_time_utc), 0)
            if capacity < 1:
                reason = "receiver_capacity_unavailable"

        if reason is not None:
            failed = self._event(
                LedgerEventType.SELECTION_FAILED,
                outcome.evaluation_time_utc,
                correlation_id=outcome.candidate_id,
                causation_event_id=selection.event_id,
                offer_id=offer.offer_id,
                receiver_site_id=offer.receiver_site_id,
                amount_mcu=offer.amount_mcu,
                reason_code=reason,
                sequence_offset=1,
            )
            self._append_batch((selection, failed))
            return ReservationAttempt(False, reason, None, selection.event_id)

        reservation_id = f"reservation:{offer.offer_id}"
        capacity_event = self._event(
            LedgerEventType.RECEIVER_CAPACITY_RESERVED,
            outcome.evaluation_time_utc,
            correlation_id=outcome.candidate_id,
            causation_event_id=selection.event_id,
            offer_id=offer.offer_id,
            reservation_id=reservation_id,
            receiver_site_id=offer.receiver_site_id,
            capacity_units=1,
            sequence_offset=1,
        )
        credit_event = self._event(
            LedgerEventType.CREDIT_RESERVED,
            outcome.evaluation_time_utc,
            correlation_id=outcome.candidate_id,
            causation_event_id=selection.event_id,
            offer_id=offer.offer_id,
            reservation_id=reservation_id,
            receiver_site_id=offer.receiver_site_id,
            amount_mcu=offer.amount_mcu,
            sequence_offset=2,
        )
        self._append_batch((selection, capacity_event, credit_event))
        return ReservationAttempt(True, "reservation_succeeded", reservation_id,
                                  selection.event_id)

    def complete_receiver_start(self, reservation_id, *, at):
        snapshot = self.snapshot
        status = dict(snapshot.reservation_statuses).get(reservation_id)
        if status != "active":
            raise ValueError("Receiver start requires an active reservation")
        reservation = _reservation_metadata(self.events, reservation_id)
        start = self._event(
            LedgerEventType.SIMULATED_RECEIVER_START, at,
            correlation_id=reservation.correlation_id,
            causation_event_id=reservation.event_id,
            offer_id=reservation.offer_id,
            reservation_id=reservation_id,
            receiver_site_id=reservation.receiver_site_id,
            capacity_units=1,
        )
        issuance_id = f"issuance:{reservation.offer_id}"
        issued = self._event(
            LedgerEventType.CREDIT_ISSUED, at,
            correlation_id=reservation.correlation_id,
            causation_event_id=start.event_id,
            offer_id=reservation.offer_id,
            reservation_id=reservation_id,
            issuance_id=issuance_id,
            receiver_site_id=reservation.receiver_site_id,
            amount_mcu=reservation.amount_mcu,
            sequence_offset=1,
        )
        self._append_batch((start, issued))
        return issued

    def release_reservation(self, reservation_id, *, at, reason_code):
        snapshot = self.snapshot
        if dict(snapshot.reservation_statuses).get(reservation_id) != "active":
            raise ValueError("Reservation release requires an active reservation")
        reservation = _reservation_metadata(self.events, reservation_id)
        capacity = self._event(
            LedgerEventType.RECEIVER_CAPACITY_RELEASED, at,
            correlation_id=reservation.correlation_id,
            causation_event_id=reservation.event_id,
            offer_id=reservation.offer_id,
            reservation_id=reservation_id,
            receiver_site_id=reservation.receiver_site_id,
            capacity_units=1,
            reason_code=reason_code,
        )
        credit = self._event(
            LedgerEventType.CREDIT_RESERVATION_RELEASED, at,
            correlation_id=reservation.correlation_id,
            causation_event_id=reservation.event_id,
            offer_id=reservation.offer_id,
            reservation_id=reservation_id,
            receiver_site_id=reservation.receiver_site_id,
            amount_mcu=reservation.amount_mcu,
            reason_code=reason_code,
            sequence_offset=1,
        )
        failed = self._event(
            LedgerEventType.SELECTION_FAILED, at,
            correlation_id=reservation.correlation_id,
            causation_event_id=credit.event_id,
            offer_id=reservation.offer_id,
            reservation_id=reservation_id,
            receiver_site_id=reservation.receiver_site_id,
            reason_code=reason_code,
            sequence_offset=2,
        )
        self._append_batch((capacity, credit, failed))

    def redeem(self, issuance_id, amount_mcu, *, at):
        snapshot = self.snapshot
        remaining = dict(snapshot.issuance_remaining).get(issuance_id)
        if remaining is None or remaining <= 0:
            raise ValueError("Redemption requires an outstanding issuance")
        if (isinstance(amount_mcu, bool) or not isinstance(amount_mcu, int)
                or amount_mcu <= 0 or amount_mcu > remaining):
            raise ValueError("Redemption amount exceeds outstanding issuance")
        issuance = _issuance_metadata(self.events, issuance_id)
        event_type = (
            LedgerEventType.CREDIT_FULLY_REDEEMED
            if amount_mcu == remaining
            else LedgerEventType.CREDIT_PARTIALLY_REDEEMED
        )
        event = self._event(
            event_type, at,
            correlation_id=issuance.correlation_id,
            causation_event_id=issuance.event_id,
            offer_id=issuance.offer_id,
            reservation_id=issuance.reservation_id,
            issuance_id=issuance_id,
            amount_mcu=amount_mcu,
        )
        self._append_batch((event,))
        return event

    def close_outstanding_credit(self, issuance_id, *, at, outcome, reason_code):
        event_types = {
            "expired": LedgerEventType.CREDIT_EXPIRED,
            "reversed": LedgerEventType.CREDIT_REVERSED,
        }
        if outcome not in event_types:
            raise ValueError("Unsupported outstanding-credit terminal outcome")
        remaining = dict(self.snapshot.issuance_remaining).get(issuance_id)
        if remaining is None or remaining <= 0:
            raise ValueError("Credit closure requires an outstanding issuance")
        issuance = _issuance_metadata(self.events, issuance_id)
        event = self._event(
            event_types[outcome], at,
            correlation_id=issuance.correlation_id,
            causation_event_id=issuance.event_id,
            offer_id=issuance.offer_id,
            reservation_id=issuance.reservation_id,
            issuance_id=issuance_id,
            amount_mcu=remaining,
            reason_code=reason_code,
        )
        self._append_batch((event,))
        return event


def _reservation_metadata(events, reservation_id):
    return next(
        event for event in reversed(events)
        if event.event_type is LedgerEventType.CREDIT_RESERVED
        and event.reservation_id == reservation_id
    )


def _issuance_metadata(events, issuance_id):
    return next(
        event for event in reversed(events)
        if event.event_type is LedgerEventType.CREDIT_ISSUED
        and event.issuance_id == issuance_id
    )


def replay_simulation_ledger(events, *, reserve_ratio):
    """Rebuild all balances from immutable events and enforce lifecycle rules."""
    rows = tuple(events)
    if (isinstance(reserve_ratio, bool)
            or not isinstance(reserve_ratio, (int, float))
            or not math.isfinite(reserve_ratio) or not 0 <= reserve_ratio <= 1):
        raise ValueError("Ledger reserve ratio must be in [0, 1]")
    if not rows:
        return SimulationLedgerSnapshot(
            funded_mcu=0, available_mcu=0, reserved_mcu=0,
            outstanding_mcu=0, settled_mcu=0, reserve_target_mcu=0,
            offerable_mcu=0, receiver_available=(), receiver_reserved=(),
            receiver_consumed=(), offer_statuses=(), candidate_statuses=(),
            reservation_statuses=(), issuance_remaining=(),
            reconciliation_difference_mcu=0, event_count=0,
        )
    funded = available = reserved = outstanding = settled = 0
    receiver_available = {}
    receiver_reserved = {}
    receiver_consumed = {}
    offers = {}
    candidates = {}
    offer_amount = {}
    reservations = {}
    reservation_amount = {}
    reservation_receiver = {}
    reservation_time = {}
    issuances = {}
    prior_ids = set()
    scenario = rows[0].scenario_id
    replication = rows[0].replication_index
    previous_time = None
    for index, event in enumerate(rows):
        event.validate()
        if event.sequence_number != index:
            raise ValueError("Ledger sequence numbers must be contiguous")
        if event.scenario_id != scenario or event.replication_index != replication:
            raise ValueError("Ledger cannot mix scenario wallets")
        if previous_time is not None and event.event_time_utc < previous_time:
            raise ValueError("Ledger event time cannot move backwards")
        if event.event_id in prior_ids:
            raise ValueError("Ledger event IDs must be unique")
        if event.causation_event_id is not None and event.causation_event_id not in prior_ids:
            raise ValueError("Ledger causation must reference an earlier event")
        prior_ids.add(event.event_id)
        previous_time = event.event_time_utc
        kind = event.event_type
        if kind in (
            LedgerEventType.OPENING_BALANCE_FUNDED,
            LedgerEventType.EXTERNAL_SUBSIDY_FUNDED,
            LedgerEventType.CONTRIBUTION_ACCRUED,
        ):
            if event.amount_mcu is None:
                raise ValueError("Funding event requires MCU amount")
            funded += event.amount_mcu
            available += event.amount_mcu
        elif kind is LedgerEventType.CONTRIBUTION_REVERSED:
            if event.amount_mcu is None or available < event.amount_mcu:
                raise ValueError("Funding reversal exceeds available MCU")
            funded -= event.amount_mcu
            available -= event.amount_mcu
        elif kind is LedgerEventType.RECEIVER_CAPACITY_OPENED:
            if not event.receiver_site_id or event.capacity_units is None:
                raise ValueError("Capacity opening requires receiver and units")
            key = (event.receiver_site_id, event.event_time_utc)
            if key in receiver_available:
                raise ValueError("Receiver capacity can be opened once per timestamp")
            receiver_available[key] = event.capacity_units
            receiver_reserved[key] = 0
            receiver_consumed[key] = 0
        elif kind is LedgerEventType.CREDIT_OFFER_CREATED:
            if (not event.offer_id or event.amount_mcu is None
                    or not event.receiver_site_id or event.expires_at_utc is None):
                raise ValueError("Offer event is incomplete")
            if event.offer_id in offers:
                raise ValueError("Offer can be created only once")
            offers[event.offer_id] = "created"
            offer_amount[event.offer_id] = event.amount_mcu
        elif kind is LedgerEventType.ALTERNATIVE_SELECTED:
            if offers.get(event.offer_id) != "created":
                raise ValueError("Selection requires a live created offer")
            if event.correlation_id in candidates:
                raise ValueError("Candidate already has a choice outcome")
            offers[event.offer_id] = "selected"
            candidates[event.correlation_id] = "alternative_selected"
        elif kind is LedgerEventType.SELECTION_FAILED:
            if offers.get(event.offer_id) not in ("selected", "released"):
                raise ValueError("Selection failure requires selected or released offer")
            if candidates.get(event.correlation_id) != "alternative_selected":
                raise ValueError("Selection failure requires selected candidate")
            offers[event.offer_id] = "selection_failed"
            candidates[event.correlation_id] = "selection_failed"
        elif kind in (
            LedgerEventType.CREDIT_OFFER_DECLINED,
            LedgerEventType.CREDIT_OFFER_EXPIRED,
            LedgerEventType.CREDIT_OFFER_WITHDRAWN,
        ):
            if offers.get(event.offer_id) != "created":
                raise ValueError("Offer terminal event requires a live created offer")
            offers[event.offer_id] = kind.value
        elif kind is LedgerEventType.RECEIVER_CAPACITY_RESERVED:
            key = (event.receiver_site_id, event.event_time_utc)
            if (event.reservation_id in reservations or event.capacity_units != 1
                    or receiver_available.get(key, 0) < 1):
                raise ValueError("Receiver capacity reservation is invalid")
            receiver_available[key] -= 1
            receiver_reserved[key] += 1
            reservations[event.reservation_id] = "capacity_only"
            reservation_receiver[event.reservation_id] = event.receiver_site_id
            reservation_time[event.reservation_id] = event.event_time_utc
        elif kind is LedgerEventType.CREDIT_RESERVED:
            if (offers.get(event.offer_id) != "selected"
                    or reservations.get(event.reservation_id) != "capacity_only"
                    or event.amount_mcu != offer_amount[event.offer_id]):
                raise ValueError("Credit reservation does not match selection and capacity")
            reserve_target = math.ceil(reserve_ratio*(available+reserved+outstanding))
            if available-reserve_target < event.amount_mcu:
                raise ValueError("Credit reservation exceeds offerable MCU")
            available -= event.amount_mcu
            reserved += event.amount_mcu
            reservations[event.reservation_id] = "active"
            reservation_amount[event.reservation_id] = event.amount_mcu
            offers[event.offer_id] = "reserved"
        elif kind is LedgerEventType.RECEIVER_CAPACITY_RELEASED:
            if reservations.get(event.reservation_id) != "active":
                raise ValueError("Capacity release requires active reservation")
            key = (event.receiver_site_id, reservation_time[event.reservation_id])
            if receiver_reserved.get(key, 0) < 1:
                raise ValueError("Receiver reserved capacity is unavailable")
            receiver_reserved[key] -= 1
            receiver_available[key] += 1
            reservations[event.reservation_id] = "capacity_released"
        elif kind is LedgerEventType.CREDIT_RESERVATION_RELEASED:
            if reservations.get(event.reservation_id) != "capacity_released":
                raise ValueError("Credit release must follow capacity release")
            amount = reservation_amount[event.reservation_id]
            if event.amount_mcu != amount or reserved < amount:
                raise ValueError("Credit reservation release amount is inconsistent")
            reserved -= amount
            available += amount
            reservations[event.reservation_id] = "released"
            offers[event.offer_id] = "released"
        elif kind is LedgerEventType.SIMULATED_RECEIVER_START:
            if reservations.get(event.reservation_id) != "active":
                raise ValueError("Receiver start requires active reservation")
            key = (event.receiver_site_id, reservation_time[event.reservation_id])
            if receiver_reserved.get(key, 0) < 1:
                raise ValueError("Receiver start lacks reserved capacity")
            receiver_reserved[key] -= 1
            receiver_consumed[key] += 1
            reservations[event.reservation_id] = "receiver_started"
        elif kind is LedgerEventType.CREDIT_ISSUED:
            if (reservations.get(event.reservation_id) != "receiver_started"
                    or event.issuance_id in issuances):
                raise ValueError("Credit issuance requires completed reserved action")
            amount = reservation_amount[event.reservation_id]
            if event.amount_mcu != amount or reserved < amount:
                raise ValueError("Credit issuance amount is inconsistent")
            reserved -= amount
            outstanding += amount
            reservations[event.reservation_id] = "issued"
            offers[event.offer_id] = "issued"
            issuances[event.issuance_id] = amount
        elif kind in (
            LedgerEventType.CREDIT_PARTIALLY_REDEEMED,
            LedgerEventType.CREDIT_FULLY_REDEEMED,
        ):
            remaining = issuances.get(event.issuance_id)
            if remaining is None or event.amount_mcu is None or event.amount_mcu > remaining:
                raise ValueError("Credit redemption exceeds issuance")
            if (kind is LedgerEventType.CREDIT_PARTIALLY_REDEEMED
                    and event.amount_mcu >= remaining):
                raise ValueError("Partial redemption must leave positive balance")
            if (kind is LedgerEventType.CREDIT_FULLY_REDEEMED
                    and event.amount_mcu != remaining):
                raise ValueError("Full redemption must consume remaining issuance")
            issuances[event.issuance_id] -= event.amount_mcu
            outstanding -= event.amount_mcu
            settled += event.amount_mcu
        elif kind in (LedgerEventType.CREDIT_EXPIRED, LedgerEventType.CREDIT_REVERSED):
            remaining = issuances.get(event.issuance_id)
            if remaining is None or remaining <= 0 or event.amount_mcu != remaining:
                raise ValueError("Credit expiry/reversal must consume remaining issuance")
            issuances[event.issuance_id] = 0
            outstanding -= remaining
            available += remaining
        elif kind is LedgerEventType.CANDIDATE_UNASSIGNED:
            if not event.reason_code:
                raise ValueError("Unassigned candidate requires a reason")
            if event.correlation_id in candidates:
                raise ValueError("Candidate already has a choice outcome")
            candidates[event.correlation_id] = "candidate_unassigned"
        else:  # pragma: no cover - exhaustive enum guard
            raise ValueError(f"Unsupported ledger event type: {kind}")
        if min(funded, available, reserved, outstanding, settled) < 0:
            raise ValueError("Ledger event creates a negative balance")
        if funded != available+reserved+outstanding+settled:
            raise ValueError("Ledger funding identity was violated")

    reserve_target = math.ceil(reserve_ratio*(available+reserved+outstanding))
    snapshot = SimulationLedgerSnapshot(
        funded_mcu=funded,
        available_mcu=available,
        reserved_mcu=reserved,
        outstanding_mcu=outstanding,
        settled_mcu=settled,
        reserve_target_mcu=reserve_target,
        offerable_mcu=max(0, available-reserve_target),
        receiver_available=tuple(
            (site, at, value) for (site, at), value
            in sorted(receiver_available.items(), key=lambda item: item[0])
        ),
        receiver_reserved=tuple(
            (site, at, value) for (site, at), value
            in sorted(receiver_reserved.items(), key=lambda item: item[0])
        ),
        receiver_consumed=tuple(
            (site, at, value) for (site, at), value
            in sorted(receiver_consumed.items(), key=lambda item: item[0])
        ),
        offer_statuses=tuple(sorted(offers.items())),
        candidate_statuses=tuple(sorted(candidates.items())),
        reservation_statuses=tuple(sorted(reservations.items())),
        issuance_remaining=tuple(sorted(issuances.items())),
        reconciliation_difference_mcu=(
            funded-available-reserved-outstanding-settled
        ),
        event_count=len(rows),
    )
    snapshot.validate()
    return snapshot
