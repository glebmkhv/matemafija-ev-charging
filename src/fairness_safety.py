"""Observable safety gates and non-demographic distributional proxy audit."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from statistics import fmean

try:
    from .receiver_choice import (
        FundedReceiverOffer, ReceiverChoiceOutcome,
        ReceiverChoiceOutcomeType,
    )
    from .simulation_contract import ClaimScope, ProvenanceClass
    from .simulation_grid import RedistributionCandidate
    from .simulation_ledger import SimulationLedgerSnapshot
except ImportError:  # pragma: no cover
    from receiver_choice import (
        FundedReceiverOffer, ReceiverChoiceOutcome,
        ReceiverChoiceOutcomeType,
    )
    from simulation_contract import ClaimScope, ProvenanceClass
    from simulation_grid import RedistributionCandidate
    from simulation_ledger import SimulationLedgerSnapshot


FAIRNESS_SAFETY_VERSION = "1.0.0"


class GuardStatus(str, Enum):
    PASS = "pass"
    BLOCK = "block"
    NOT_EVALUABLE = "not_evaluable"


@dataclass(frozen=True)
class FairnessSafetySpecification:
    maximum_offer_mcu: int = 25
    maximum_distance_km: float = 5.0
    minimum_receiver_availability_ratio: float = 0.5
    minimum_residual_receiver_capacity: int = 1
    minimum_batch_candidates_for_distributional_claim: int = 20
    maximum_no_offer_share: float = 0.50
    maximum_receiver_offer_count_share: float = 0.60
    maximum_safety_block_share: float = 0.0
    provenance: ProvenanceClass = ProvenanceClass.POLICY_DEFINED

    def validate(self):
        integer_values = (
            self.maximum_offer_mcu,
            self.minimum_residual_receiver_capacity,
            self.minimum_batch_candidates_for_distributional_claim,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in integer_values):
            raise ValueError("Fairness/safety integer parameters must be non-negative")
        if self.maximum_offer_mcu <= 0:
            raise ValueError("Maximum offer must be positive")
        if self.minimum_batch_candidates_for_distributional_claim <= 0:
            raise ValueError("Distributional minimum batch must be positive")
        if (not math.isfinite(self.maximum_distance_km)
                or self.maximum_distance_km <= 0):
            raise ValueError("Maximum distance must be finite and positive")
        ratios = (
            self.minimum_receiver_availability_ratio,
            self.maximum_no_offer_share,
            self.maximum_receiver_offer_count_share,
            self.maximum_safety_block_share,
        )
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in ratios):
            raise ValueError("Fairness/safety ratios must be in [0, 1]")
        if self.provenance is not ProvenanceClass.POLICY_DEFINED:
            raise ValueError("Fairness/safety thresholds must be policy-defined")


@dataclass(frozen=True)
class OfferSafetyDecision:
    candidate_id: str
    offer_id: str
    receiver_site_id: str
    evaluation_time_utc: datetime
    status: GuardStatus
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    receiver_available_before: int
    receiver_available_after: int
    pool_offerable_before_mcu: int
    requested_mcu: int
    personalized_recommendation_allowed: bool = False
    demographic_fairness_evaluable: bool = False
    claim_scope: ClaimScope = ClaimScope.SCENARIO_CONDITIONAL
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    guard_version: str = FAIRNESS_SAFETY_VERSION

    @property
    def reservation_allowed(self):
        return self.status is GuardStatus.PASS

    def validate(self):
        if not all((self.candidate_id, self.offer_id, self.receiver_site_id,
                    self.guard_version)):
            raise ValueError("Offer safety decision identity is incomplete")
        if self.evaluation_time_utc.tzinfo is None:
            raise ValueError("Offer safety timestamp must include a timezone")
        values = (
            self.receiver_available_before, self.receiver_available_after,
            self.pool_offerable_before_mcu, self.requested_mcu,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in values):
            raise ValueError("Offer safety quantities must be non-negative integers")
        if self.receiver_available_after != max(0, self.receiver_available_before-1):
            raise ValueError("Offer safety residual capacity is inconsistent")
        if len(self.blocking_reasons) != len(set(self.blocking_reasons)):
            raise ValueError("Offer safety blocking reasons must be unique")
        if len(self.warnings) != len(set(self.warnings)):
            raise ValueError("Offer safety warnings must be unique")
        if self.status is GuardStatus.PASS and self.blocking_reasons:
            raise ValueError("Passing safety decision cannot contain blockers")
        if self.status is GuardStatus.BLOCK and not self.blocking_reasons:
            raise ValueError("Blocked safety decision requires a reason")
        if self.status is GuardStatus.NOT_EVALUABLE:
            raise ValueError("Individual offer safety must resolve to pass or block")
        if self.personalized_recommendation_allowed:
            raise ValueError("Current public-data MVP cannot make personalized recommendations")
        if self.demographic_fairness_evaluable:
            raise ValueError("Current public-data MVP cannot evaluate demographic fairness")
        if self.claim_scope is not ClaimScope.SCENARIO_CONDITIONAL:
            raise ValueError("Offer safety decision must remain scenario-conditional")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Offer safety decision must be simulated")


@dataclass(frozen=True)
class DistributionalProxyAudit:
    total_candidate_count: int
    candidates_with_offer_count: int
    no_offer_candidate_count: int
    no_offer_share: float
    offer_count: int
    receiver_count: int
    maximum_receiver_offer_count_share: float
    mean_offer_mcu: float | None
    mean_distance_km: float | None
    p95_distance_km: float | None
    evaluated_choice_count: int
    outside_outcome_count: int
    outside_outcome_share: float | None
    safety_decision_count: int
    safety_block_count: int
    safety_block_share: float | None
    warning_counts: tuple[tuple[str, int], ...]
    status: GuardStatus
    blocking_reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    demographic_fairness_evaluable: bool = False
    claim_scope: ClaimScope = ClaimScope.SCENARIO_CONDITIONAL
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    audit_version: str = FAIRNESS_SAFETY_VERSION

    def validate(self):
        counts = (
            self.total_candidate_count, self.candidates_with_offer_count,
            self.no_offer_candidate_count, self.offer_count, self.receiver_count,
            self.evaluated_choice_count, self.outside_outcome_count,
            self.safety_decision_count, self.safety_block_count,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in counts):
            raise ValueError("Distributional audit counts must be non-negative")
        if self.candidates_with_offer_count+self.no_offer_candidate_count != self.total_candidate_count:
            raise ValueError("Distributional candidate counts do not reconcile")
        for value in (
            self.no_offer_share, self.maximum_receiver_offer_count_share,
            self.outside_outcome_share, self.safety_block_share,
        ):
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("Distributional audit shares must be in [0, 1]")
        if self.status is GuardStatus.PASS and self.blocking_reasons:
            raise ValueError("Passing distributional audit cannot contain blockers")
        if self.status is GuardStatus.BLOCK and not self.blocking_reasons:
            raise ValueError("Blocked distributional audit requires reasons")
        if self.status is GuardStatus.NOT_EVALUABLE and not self.limitations:
            raise ValueError("Non-evaluable distributional audit requires limitations")
        if self.demographic_fairness_evaluable:
            raise ValueError("Demographic fairness is unavailable without relevant evidence")
        if self.claim_scope is not ClaimScope.SCENARIO_CONDITIONAL:
            raise ValueError("Distributional audit must remain scenario-conditional")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Distributional audit must be simulated")


def evaluate_offer_safety(
    candidate: RedistributionCandidate,
    offer: FundedReceiverOffer,
    ledger_snapshot: SimulationLedgerSnapshot,
    specification: FairnessSafetySpecification,
    *,
    evaluation_time_utc: datetime,
):
    """Evaluate observable hard guards before atomic reservation."""
    candidate.validate()
    offer.validate(candidate)
    ledger_snapshot.validate()
    specification.validate()
    if evaluation_time_utc.tzinfo is None:
        raise ValueError("Offer safety evaluation time must include a timezone")
    capacities = {
        (site, at): value for site, at, value in ledger_snapshot.receiver_available
    }
    before = capacities.get((offer.receiver_site_id, candidate.evaluation_time_utc), 0)
    after = max(0, before-1)
    blockers = []
    if evaluation_time_utc >= offer.expires_at_utc:
        blockers.append("offer_expired")
    if offer.amount_mcu > specification.maximum_offer_mcu:
        blockers.append("offer_exceeds_policy_cap")
    if offer.amount_mcu > ledger_snapshot.offerable_mcu:
        blockers.append("insufficient_offerable_mcu")
    if offer.distance_km > specification.maximum_distance_km:
        blockers.append("distance_guard_exceeded")
    if offer.receiver_availability_ratio < specification.minimum_receiver_availability_ratio:
        blockers.append("receiver_availability_below_guard")
    if before < 1:
        blockers.append("receiver_capacity_unavailable")
    elif after < specification.minimum_residual_receiver_capacity:
        blockers.append("minimum_residual_receiver_capacity_violated")
    if ledger_snapshot.reconciliation_difference_mcu != 0:
        blockers.append("ledger_reconciliation_failed")
    warnings = set(offer.unresolved_warnings)
    warnings.update((
        "demographic_fairness_not_evaluable",
        "not_a_personalized_route_recommendation",
    ))
    result = OfferSafetyDecision(
        candidate_id=candidate.candidate_id,
        offer_id=offer.offer_id,
        receiver_site_id=offer.receiver_site_id,
        evaluation_time_utc=evaluation_time_utc,
        status=GuardStatus.BLOCK if blockers else GuardStatus.PASS,
        blocking_reasons=tuple(sorted(set(blockers))),
        warnings=tuple(sorted(warnings)),
        receiver_available_before=before,
        receiver_available_after=after,
        pool_offerable_before_mcu=ledger_snapshot.offerable_mcu,
        requested_mcu=offer.amount_mcu,
    )
    result.validate()
    return result


def audit_distributional_proxies(
    *,
    total_candidate_count: int,
    offers,
    outcomes,
    safety_decisions,
    specification: FairnessSafetySpecification,
):
    """Audit observable allocation proxies without claiming group fairness."""
    specification.validate()
    if (isinstance(total_candidate_count, bool)
            or not isinstance(total_candidate_count, int)
            or total_candidate_count < 0):
        raise ValueError("Total candidate count must be a non-negative integer")
    offer_rows = tuple(offers)
    outcome_rows = tuple(outcomes)
    safety_rows = tuple(safety_decisions)
    offer_ids = {item.offer_id for item in offer_rows}
    if len(offer_ids) != len(offer_rows):
        raise ValueError("Distributional audit offer IDs must be unique")
    candidate_ids = {item.candidate_id for item in offer_rows}
    if len(candidate_ids) > total_candidate_count:
        raise ValueError("Offered candidates exceed total candidates")
    for outcome in outcome_rows:
        outcome.validate()
    for decision in safety_rows:
        decision.validate()
    decision_offer_ids = {item.offer_id for item in safety_rows}
    safety_coverage_complete = (
        len(decision_offer_ids) == len(safety_rows)
        and decision_offer_ids == offer_ids
    )
    receiver_counts = {}
    warning_counts = {}
    for item in offer_rows:
        receiver_counts[item.receiver_site_id] = receiver_counts.get(item.receiver_site_id, 0)+1
        for warning in item.unresolved_warnings:
            warning_counts[warning] = warning_counts.get(warning, 0)+1
    no_offer = total_candidate_count-len(candidate_ids)
    no_offer_share = no_offer/total_candidate_count if total_candidate_count else 0.0
    max_receiver_share = (
        max(receiver_counts.values())/len(offer_rows) if offer_rows else 0.0
    )
    outside = sum(
        item.outcome_type is ReceiverChoiceOutcomeType.OUTSIDE_UNASSIGNED
        for item in outcome_rows
    )
    blocked = sum(item.status is GuardStatus.BLOCK for item in safety_rows)
    distances = sorted(item.distance_km for item in offer_rows)
    p95_index = max(0, math.ceil(.95*len(distances))-1) if distances else None
    limitations = [
        "demographic_attributes_unavailable",
        "individual_accessibility_needs_unverified",
        "straight_line_distance_is_not_travel_time",
    ]
    blockers = []
    enough = total_candidate_count >= specification.minimum_batch_candidates_for_distributional_claim
    if enough:
        if not safety_coverage_complete:
            blockers.append("safety_decision_coverage_incomplete")
        if no_offer_share > specification.maximum_no_offer_share:
            blockers.append("no_offer_share_exceeds_guard")
        if max_receiver_share > specification.maximum_receiver_offer_count_share:
            blockers.append("receiver_offer_concentration_exceeds_guard")
        block_share = blocked/len(safety_rows) if safety_rows else None
        if block_share is not None and block_share > specification.maximum_safety_block_share:
            blockers.append("safety_block_share_exceeds_guard")
        status = GuardStatus.BLOCK if blockers else GuardStatus.PASS
    else:
        block_share = blocked/len(safety_rows) if safety_rows else None
        status = GuardStatus.NOT_EVALUABLE
        limitations.append("candidate_sample_below_distributional_minimum")
        if not safety_coverage_complete:
            limitations.append("safety_decision_coverage_incomplete")
    result = DistributionalProxyAudit(
        total_candidate_count=total_candidate_count,
        candidates_with_offer_count=len(candidate_ids),
        no_offer_candidate_count=no_offer,
        no_offer_share=no_offer_share,
        offer_count=len(offer_rows),
        receiver_count=len(receiver_counts),
        maximum_receiver_offer_count_share=max_receiver_share,
        mean_offer_mcu=fmean(item.amount_mcu for item in offer_rows) if offer_rows else None,
        mean_distance_km=fmean(distances) if distances else None,
        p95_distance_km=distances[p95_index] if p95_index is not None else None,
        evaluated_choice_count=len(outcome_rows),
        outside_outcome_count=outside,
        outside_outcome_share=outside/len(outcome_rows) if outcome_rows else None,
        safety_decision_count=len(safety_rows),
        safety_block_count=blocked,
        safety_block_share=block_share,
        warning_counts=tuple(sorted(warning_counts.items())),
        status=status,
        blocking_reasons=tuple(sorted(blockers)),
        limitations=tuple(sorted(set(limitations))),
    )
    result.validate()
    return result
