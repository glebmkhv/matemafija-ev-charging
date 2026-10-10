"""Credit-sensitive, assumption-driven choice over immutable receiver offers."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math

try:
    from .simulation_contract import ClaimScope, ProvenanceClass
    from .simulation_grid import RedistributionCandidate
except ImportError:  # pragma: no cover
    from simulation_contract import ClaimScope, ProvenanceClass
    from simulation_grid import RedistributionCandidate


RECEIVER_CHOICE_VERSION = "1.0.0"
MAXIMUM_OFFERS_PER_CHOICE = 3
MINIMUM_OFFER_MCU = 1
MAXIMUM_OFFER_MCU = 25
MAXIMUM_DISTANCE_KM = 5.0
MINIMUM_RECEIVER_AVAILABILITY = 0.5


class ReceiverChoiceOutcomeType(str, Enum):
    RECEIVER_SELECTED = "receiver_selected_pending_reservation"
    OUTSIDE_UNASSIGNED = "outside_unassigned"


@dataclass(frozen=True)
class ReceiverChoiceSpecification:
    beta_credit_per_mcu: float
    beta_distance_per_km: float
    beta_availability: float = 0.0
    receiver_availability_visible: bool = False
    model_id: str = "assumed-credit-sensitive-receiver-choice"
    model_version: str = RECEIVER_CHOICE_VERSION
    outside_utility: float = 0.0
    provenance: ProvenanceClass = ProvenanceClass.ASSUMED

    def validate(self):
        if not self.model_id or not self.model_version:
            raise ValueError("Receiver-choice response identity is required")
        values = (
            self.beta_credit_per_mcu,
            self.beta_distance_per_km,
            self.beta_availability,
            self.outside_utility,
        )
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in values):
            raise ValueError("Receiver-choice parameters must be finite numeric")
        if min(
            self.beta_credit_per_mcu,
            self.beta_distance_per_km,
            self.beta_availability,
        ) < 0:
            raise ValueError("Receiver-choice sensitivities must be non-negative")
        if self.outside_utility != 0:
            raise ValueError("Receiver-choice v1 requires zero reference outside utility")
        if not self.receiver_availability_visible and self.beta_availability != 0:
            raise ValueError(
                "Availability sensitivity requires an explicit visibility assumption"
            )
        if self.provenance is not ProvenanceClass.ASSUMED:
            raise ValueError("Receiver-choice parameters must have assumed provenance")


@dataclass(frozen=True)
class FundedReceiverOffer:
    offer_id: str
    candidate_id: str
    origin_site_id: str
    receiver_site_id: str
    allocation_rank: int
    amount_mcu: int
    distance_km: float
    receiver_availability_ratio: float
    receiver_scarcity_ratio: float
    created_at_utc: datetime
    expires_at_utc: datetime
    eligibility_decision_id: str
    allocation_batch_id: str
    allocation_contract_version: str
    distance_provenance: ProvenanceClass = ProvenanceClass.RECONSTRUCTED
    receiver_state_provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    unresolved_warnings: tuple[str, ...] = (
        "vehicle_connector_compatibility_unverified",
        "road_travel_time_unavailable",
        "individual_accessibility_needs_unverified",
        "cross_operator_acceptance_unverified",
        "total_session_cost_unavailable",
    )

    def validate(self, candidate: RedistributionCandidate):
        identity = (
            self.offer_id, self.candidate_id, self.origin_site_id,
            self.receiver_site_id, self.eligibility_decision_id,
            self.allocation_batch_id, self.allocation_contract_version,
        )
        if not all(identity):
            raise ValueError("Funded receiver offer identity is incomplete")
        if self.candidate_id != candidate.candidate_id:
            raise ValueError("Receiver offer belongs to another candidate")
        if self.origin_site_id != candidate.origin_site_id:
            raise ValueError("Receiver offer belongs to another origin")
        if self.receiver_site_id == self.origin_site_id:
            raise ValueError("Receiver offer cannot point back to its origin")
        if (isinstance(self.allocation_rank, bool)
                or not isinstance(self.allocation_rank, int)
                or self.allocation_rank <= 0):
            raise ValueError("Receiver offer allocation rank must be a positive integer")
        if (isinstance(self.amount_mcu, bool) or not isinstance(self.amount_mcu, int)
                or not MINIMUM_OFFER_MCU <= self.amount_mcu <= MAXIMUM_OFFER_MCU):
            raise ValueError("Receiver offer must contain 1--25 integer MCU")
        values = (
            self.distance_km,
            self.receiver_availability_ratio,
            self.receiver_scarcity_ratio,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Receiver offer choice attributes must be finite")
        if not 0 <= self.distance_km <= MAXIMUM_DISTANCE_KM:
            raise ValueError("Receiver offer distance must remain within the 5 km gate")
        if (not 0 <= self.receiver_availability_ratio <= 1
                or not 0 <= self.receiver_scarcity_ratio <= 1):
            raise ValueError("Receiver availability and scarcity must be in [0, 1]")
        if not math.isclose(
            self.receiver_scarcity_ratio,
            1-self.receiver_availability_ratio,
            rel_tol=1e-12, abs_tol=1e-12,
        ):
            raise ValueError("Receiver scarcity must complement availability")
        if self.receiver_availability_ratio < MINIMUM_RECEIVER_AVAILABILITY:
            raise ValueError("Receiver offer fails the v1 availability gate")
        if self.created_at_utc.tzinfo is None or self.expires_at_utc.tzinfo is None:
            raise ValueError("Receiver offer timestamps must include timezones")
        if self.created_at_utc != candidate.evaluation_time_utc:
            raise ValueError("Receiver offer must use the candidate decision timestamp")
        if self.expires_at_utc <= self.created_at_utc:
            raise ValueError("Receiver offer expiry must follow creation")
        if self.distance_provenance not in (
            ProvenanceClass.OBSERVED, ProvenanceClass.RECONSTRUCTED,
        ):
            raise ValueError("Offer distance must be observed or reconstructed")
        if self.receiver_state_provenance not in (
            ProvenanceClass.RECONSTRUCTED, ProvenanceClass.SIMULATED,
        ):
            raise ValueError("Receiver state provenance is invalid")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Funded receiver offer must be simulated")
        if (len(self.unresolved_warnings) != len(set(self.unresolved_warnings))
                or any(not item for item in self.unresolved_warnings)):
            raise ValueError("Receiver offer warnings must be non-empty and unique")


@dataclass(frozen=True)
class ReceiverChoiceAlternativeProbability:
    offer_id: str
    receiver_site_id: str
    allocation_rank: int
    amount_mcu: int
    distance_km: float
    receiver_availability_ratio: float
    credit_utility_component: float
    distance_utility_component: float
    availability_utility_component: float
    systematic_utility: float
    probability: float

    def validate(self):
        if not self.offer_id or not self.receiver_site_id:
            raise ValueError("Receiver-choice alternative identity is incomplete")
        if (isinstance(self.allocation_rank, bool)
                or not isinstance(self.allocation_rank, int)
                or self.allocation_rank <= 0):
            raise ValueError("Receiver-choice alternative rank is invalid")
        if (isinstance(self.amount_mcu, bool) or not isinstance(self.amount_mcu, int)
                or not MINIMUM_OFFER_MCU <= self.amount_mcu <= MAXIMUM_OFFER_MCU):
            raise ValueError("Receiver-choice alternative MCU amount is invalid")
        values = (
            self.distance_km, self.receiver_availability_ratio,
            self.credit_utility_component, self.distance_utility_component,
            self.availability_utility_component, self.systematic_utility,
            self.probability,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Receiver-choice alternative values must be finite")
        if not 0 <= self.probability <= 1:
            raise ValueError("Receiver-choice probability must be in [0, 1]")
        if not math.isclose(
            self.systematic_utility,
            self.credit_utility_component
            + self.distance_utility_component
            + self.availability_utility_component,
            rel_tol=1e-12, abs_tol=1e-12,
        ):
            raise ValueError("Receiver-choice utility components do not reconcile")


@dataclass(frozen=True)
class ReceiverChoiceEvaluation:
    candidate_id: str
    scenario_id: str
    replication_index: int
    evaluation_time_utc: datetime
    alternatives: tuple[ReceiverChoiceAlternativeProbability, ...]
    outside_probability: float
    probability_sum: float
    beta_credit_per_mcu: float
    beta_distance_per_km: float
    beta_availability: float
    receiver_availability_visible: bool
    model_id: str
    model_version: str
    claim_scope: ClaimScope = ClaimScope.SCENARIO_CONDITIONAL
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    choice_contract_version: str = RECEIVER_CHOICE_VERSION

    def validate(self):
        if not self.candidate_id or not self.scenario_id:
            raise ValueError("Receiver-choice evaluation identity is incomplete")
        if not self.model_id or not self.model_version or not self.choice_contract_version:
            raise ValueError("Receiver-choice model identity is incomplete")
        if self.evaluation_time_utc.tzinfo is None:
            raise ValueError("Receiver-choice evaluation time must include a timezone")
        if not 0 <= self.outside_probability <= 1:
            raise ValueError("Outside probability must be in [0, 1]")
        coefficients = (
            self.beta_credit_per_mcu,
            self.beta_distance_per_km,
            self.beta_availability,
        )
        if any(not math.isfinite(value) or value < 0 for value in coefficients):
            raise ValueError("Receiver-choice evaluation coefficients are invalid")
        if not self.receiver_availability_visible and self.beta_availability != 0:
            raise ValueError("Hidden receiver availability cannot have a response effect")
        for alternative in self.alternatives:
            alternative.validate()
            if not math.isclose(
                alternative.credit_utility_component,
                self.beta_credit_per_mcu * alternative.amount_mcu,
                rel_tol=1e-12, abs_tol=1e-12,
            ):
                raise ValueError("Receiver-choice credit utility is inconsistent")
            if not math.isclose(
                alternative.distance_utility_component,
                -self.beta_distance_per_km * alternative.distance_km,
                rel_tol=1e-12, abs_tol=1e-12,
            ):
                raise ValueError("Receiver-choice distance utility is inconsistent")
            if not math.isclose(
                alternative.availability_utility_component,
                self.beta_availability * alternative.receiver_availability_ratio,
                rel_tol=1e-12, abs_tol=1e-12,
            ):
                raise ValueError("Receiver-choice availability utility is inconsistent")
        offer_ids = [item.offer_id for item in self.alternatives]
        receiver_ids = [item.receiver_site_id for item in self.alternatives]
        ranks = [item.allocation_rank for item in self.alternatives]
        if (len(offer_ids) != len(set(offer_ids))
                or len(receiver_ids) != len(set(receiver_ids))
                or len(ranks) != len(set(ranks))):
            raise ValueError("Receiver-choice alternatives must be unique")
        calculated = self.outside_probability + sum(
            item.probability for item in self.alternatives
        )
        if (not math.isclose(self.probability_sum, calculated, abs_tol=1e-12)
                or not math.isclose(calculated, 1.0, abs_tol=1e-12)):
            raise ValueError("Receiver-choice probabilities must sum to one")
        if self.claim_scope is not ClaimScope.SCENARIO_CONDITIONAL:
            raise ValueError("Receiver choice must remain scenario-conditional")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Receiver-choice evaluation must be simulated")


@dataclass(frozen=True)
class ReceiverChoiceOutcome:
    candidate_id: str
    scenario_id: str
    replication_index: int
    evaluation_time_utc: datetime
    random_uniform: float
    outcome_type: ReceiverChoiceOutcomeType
    selected_offer_id: str | None
    selected_receiver_site_id: str | None
    selected_amount_mcu: int | None
    reservation_required: bool
    model_id: str
    model_version: str
    claim_scope: ClaimScope = ClaimScope.SCENARIO_CONDITIONAL
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED

    def validate(self):
        if (not self.candidate_id or not self.scenario_id
                or self.evaluation_time_utc.tzinfo is None):
            raise ValueError("Receiver-choice outcome identity is incomplete")
        if not self.model_id or not self.model_version:
            raise ValueError("Receiver-choice outcome model identity is incomplete")
        if (isinstance(self.replication_index, bool)
                or not isinstance(self.replication_index, int)
                or self.replication_index < 0):
            raise ValueError("Receiver-choice replication index is invalid")
        if not 0 <= self.random_uniform < 1:
            raise ValueError("Receiver-choice random uniform must be in [0, 1)")
        selected = (
            self.selected_offer_id,
            self.selected_receiver_site_id,
            self.selected_amount_mcu,
        )
        if self.outcome_type is ReceiverChoiceOutcomeType.RECEIVER_SELECTED:
            if any(value is None for value in selected) or not self.reservation_required:
                raise ValueError("Receiver selection must remain pending reservation")
        elif self.outcome_type is ReceiverChoiceOutcomeType.OUTSIDE_UNASSIGNED:
            if any(value is not None for value in selected) or self.reservation_required:
                raise ValueError("Outside outcome cannot reserve an offer")
        else:
            raise ValueError("Unknown receiver-choice outcome")
        if self.claim_scope is not ClaimScope.SCENARIO_CONDITIONAL:
            raise ValueError("Receiver-choice outcome must remain scenario-conditional")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Receiver-choice outcome must be simulated")


def evaluate_receiver_choice(
    candidate: RedistributionCandidate,
    offers,
    specification: ReceiverChoiceSpecification,
):
    """Return deterministic probabilities; do not reserve credit or capacity."""
    candidate.validate()
    specification.validate()
    rows = tuple(offers)
    if len(rows) > MAXIMUM_OFFERS_PER_CHOICE:
        raise ValueError("Receiver choice cannot contain more than three offers")
    for offer in rows:
        offer.validate(candidate)
    offer_ids = [item.offer_id for item in rows]
    receiver_ids = [item.receiver_site_id for item in rows]
    ranks = [item.allocation_rank for item in rows]
    if (len(offer_ids) != len(set(offer_ids))
            or len(receiver_ids) != len(set(receiver_ids))
            or len(ranks) != len(set(ranks))):
        raise ValueError("Receiver choice contains duplicate offers, receivers or ranks")
    ordered = sorted(rows, key=lambda item: item.allocation_rank)

    utility_rows = []
    for offer in ordered:
        credit = specification.beta_credit_per_mcu * offer.amount_mcu
        distance = -specification.beta_distance_per_km * offer.distance_km
        availability = (
            specification.beta_availability * offer.receiver_availability_ratio
        )
        utility_rows.append((offer, credit, distance, availability,
                             credit+distance+availability))

    utility_values = [specification.outside_utility] + [
        item[4] for item in utility_rows
    ]
    shift = max(utility_values)
    weights = [math.exp(value-shift) for value in utility_values]
    denominator = sum(weights)
    outside_probability = weights[0]/denominator
    alternatives = tuple(
        ReceiverChoiceAlternativeProbability(
            offer_id=offer.offer_id,
            receiver_site_id=offer.receiver_site_id,
            allocation_rank=offer.allocation_rank,
            amount_mcu=offer.amount_mcu,
            distance_km=offer.distance_km,
            receiver_availability_ratio=offer.receiver_availability_ratio,
            credit_utility_component=credit,
            distance_utility_component=distance,
            availability_utility_component=availability,
            systematic_utility=utility,
            probability=weight/denominator,
        )
        for (offer, credit, distance, availability, utility), weight
        in zip(utility_rows, weights[1:])
    )
    result = ReceiverChoiceEvaluation(
        candidate_id=candidate.candidate_id,
        scenario_id=candidate.scenario_id,
        replication_index=candidate.replication_index,
        evaluation_time_utc=candidate.evaluation_time_utc,
        alternatives=alternatives,
        outside_probability=outside_probability,
        probability_sum=outside_probability+sum(
            item.probability for item in alternatives
        ),
        beta_credit_per_mcu=specification.beta_credit_per_mcu,
        beta_distance_per_km=specification.beta_distance_per_km,
        beta_availability=specification.beta_availability,
        receiver_availability_visible=(
            specification.receiver_availability_visible
        ),
        model_id=specification.model_id,
        model_version=specification.model_version,
    )
    result.validate()
    return result


def draw_receiver_choice(
    evaluation: ReceiverChoiceEvaluation,
    *,
    random_uniform: float,
):
    """Draw one outcome; receiver selection still requires atomic reservation."""
    evaluation.validate()
    if (isinstance(random_uniform, bool)
            or not isinstance(random_uniform, (int, float))
            or not math.isfinite(random_uniform)
            or not 0 <= random_uniform < 1):
        raise ValueError("Receiver-choice random uniform must be in [0, 1)")
    cumulative = 0.0
    selected = None
    for alternative in sorted(
        evaluation.alternatives, key=lambda item: item.allocation_rank
    ):
        cumulative += alternative.probability
        if random_uniform < cumulative:
            selected = alternative
            break
    if selected is None:
        result = ReceiverChoiceOutcome(
            candidate_id=evaluation.candidate_id,
            scenario_id=evaluation.scenario_id,
            replication_index=evaluation.replication_index,
            evaluation_time_utc=evaluation.evaluation_time_utc,
            random_uniform=float(random_uniform),
            outcome_type=ReceiverChoiceOutcomeType.OUTSIDE_UNASSIGNED,
            selected_offer_id=None,
            selected_receiver_site_id=None,
            selected_amount_mcu=None,
            reservation_required=False,
            model_id=evaluation.model_id,
            model_version=evaluation.model_version,
        )
    else:
        result = ReceiverChoiceOutcome(
            candidate_id=evaluation.candidate_id,
            scenario_id=evaluation.scenario_id,
            replication_index=evaluation.replication_index,
            evaluation_time_utc=evaluation.evaluation_time_utc,
            random_uniform=float(random_uniform),
            outcome_type=ReceiverChoiceOutcomeType.RECEIVER_SELECTED,
            selected_offer_id=selected.offer_id,
            selected_receiver_site_id=selected.receiver_site_id,
            selected_amount_mcu=selected.amount_mcu,
            reservation_required=True,
            model_id=evaluation.model_id,
            model_version=evaluation.model_version,
        )
    result.validate()
    return result
