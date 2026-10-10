"""Four-domain evaluation for paired credit-circulation simulation runs."""

from dataclasses import dataclass
from enum import Enum
import math
from statistics import fmean

try:
    from .credit_simulation_grid import (
        CreditPairedSimulationRun, CreditSimulationGridResult,
    )
    from .fairness_safety import GuardStatus
    from .receiver_choice import ReceiverChoiceOutcomeType
    from .simulation_contract import ClaimScope, ProvenanceClass
    from .simulation_evaluation import (
        PairedScarcityEvaluation, SimulationGridEvaluation,
    )
except ImportError:  # pragma: no cover
    from credit_simulation_grid import (
        CreditPairedSimulationRun, CreditSimulationGridResult,
    )
    from fairness_safety import GuardStatus
    from receiver_choice import ReceiverChoiceOutcomeType
    from simulation_contract import ClaimScope, ProvenanceClass
    from simulation_evaluation import (
        PairedScarcityEvaluation, SimulationGridEvaluation,
    )


CREDIT_SIMULATION_EVALUATION_VERSION = "1.0.0"


class MetricAvailability(str, Enum):
    AVAILABLE = "available"
    NOT_EVALUABLE = "not_evaluable"


@dataclass(frozen=True)
class SystemEvaluation:
    zero_availability_snapshot_share_change: float | None
    mean_availability_ratio_change: float | None
    mean_operational_scarcity_ratio_change: float | None
    additional_release_count: int
    deferred_or_displaced_start_proxy_count: int
    scarcity_metric_availability: MetricAvailability
    episode_metrics_availability: MetricAvailability = MetricAvailability.NOT_EVALUABLE

    def validate(self):
        values = (
            self.zero_availability_snapshot_share_change,
            self.mean_availability_ratio_change,
            self.mean_operational_scarcity_ratio_change,
        )
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("System changes must be finite when available")
        available = all(value is not None for value in values)
        if available != (self.scarcity_metric_availability is MetricAvailability.AVAILABLE):
            raise ValueError("System scarcity availability is inconsistent")
        if min(self.additional_release_count,
               self.deferred_or_displaced_start_proxy_count) < 0:
            raise ValueError("System response counts cannot be negative")
        if self.episode_metrics_availability is not MetricAvailability.NOT_EVALUABLE:
            raise ValueError("One-step projections cannot support episode metrics")


@dataclass(frozen=True)
class RedistributionEvaluation:
    candidate_count: int
    candidate_with_offer_count: int
    no_offer_candidate_count: int
    safety_pass_offer_count: int
    safety_block_offer_count: int
    selected_receiver_count: int
    outside_unassigned_count: int
    realized_redistribution_share: float | None
    outside_unassigned_share: float | None
    receiver_capacity_consumed_count: int
    residual_capacity_guard_block_count: int
    distributional_proxy_status: GuardStatus

    def validate(self):
        counts = (
            self.candidate_count, self.candidate_with_offer_count,
            self.no_offer_candidate_count, self.safety_pass_offer_count,
            self.safety_block_offer_count, self.selected_receiver_count,
            self.outside_unassigned_count,
            self.receiver_capacity_consumed_count,
            self.residual_capacity_guard_block_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("Redistribution counts cannot be negative")
        if self.candidate_with_offer_count+self.no_offer_candidate_count != self.candidate_count:
            raise ValueError("Redistribution offer coverage does not reconcile")
        if self.selected_receiver_count+self.outside_unassigned_count != self.candidate_count:
            raise ValueError("Redistribution outcomes do not reconcile")
        if self.receiver_capacity_consumed_count != self.selected_receiver_count:
            raise ValueError("Receiver capacity consumption must match realized redistribution")
        expected_realized = (
            self.selected_receiver_count/self.candidate_count
            if self.candidate_count else None
        )
        expected_outside = (
            self.outside_unassigned_count/self.candidate_count
            if self.candidate_count else None
        )
        if self.realized_redistribution_share != expected_realized:
            raise ValueError("Realized redistribution share is inconsistent")
        if self.outside_unassigned_share != expected_outside:
            raise ValueError("Outside share is inconsistent")


@dataclass(frozen=True)
class UserProxyEvaluation:
    proposed_offer_count: int
    selected_offer_count: int
    mean_proposed_credit_mcu: float | None
    mean_selected_credit_mcu: float | None
    mean_proposed_distance_km: float | None
    mean_selected_distance_km: float | None
    p95_proposed_distance_km: float | None
    unresolved_warning_count: int
    total_session_cost_availability: MetricAvailability
    travel_time_availability: MetricAvailability
    welfare_availability: MetricAvailability
    demographic_fairness_availability: MetricAvailability

    def validate(self):
        if min(self.proposed_offer_count, self.selected_offer_count,
               self.unresolved_warning_count) < 0:
            raise ValueError("User-proxy counts cannot be negative")
        if self.selected_offer_count > self.proposed_offer_count:
            raise ValueError("Selected offers cannot exceed proposed offers")
        for value in (
            self.mean_proposed_credit_mcu, self.mean_selected_credit_mcu,
            self.mean_proposed_distance_km, self.mean_selected_distance_km,
            self.p95_proposed_distance_km,
        ):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("User-proxy values must be finite and non-negative")
        unavailable = (
            self.total_session_cost_availability, self.travel_time_availability,
            self.welfare_availability, self.demographic_fairness_availability,
        )
        if any(item is not MetricAvailability.NOT_EVALUABLE for item in unavailable):
            raise ValueError("Unavailable user outcomes cannot be promoted to evaluated")


@dataclass(frozen=True)
class AccountingEvaluation:
    funded_mcu: int
    available_mcu: int
    reserved_mcu: int
    outstanding_mcu: int
    settled_mcu: int
    reserve_target_mcu: int
    offerable_mcu: int
    proposed_offer_exposure_mcu: int
    issued_mcu: int
    issuance_count: int
    reconciliation_difference_mcu: int
    solvent_and_reconciled: bool
    redemption_rate: float | None

    def validate(self):
        values = (
            self.funded_mcu, self.available_mcu, self.reserved_mcu,
            self.outstanding_mcu, self.settled_mcu,
            self.reserve_target_mcu, self.offerable_mcu,
            self.proposed_offer_exposure_mcu, self.issued_mcu,
            self.issuance_count,
        )
        if any(value < 0 for value in values):
            raise ValueError("Accounting evaluation values cannot be negative")
        expected = (
            self.funded_mcu-self.available_mcu-self.reserved_mcu
            -self.outstanding_mcu-self.settled_mcu
        )
        if expected != self.reconciliation_difference_mcu:
            raise ValueError("Accounting evaluation does not reconcile")
        if self.issued_mcu != self.outstanding_mcu+self.settled_mcu:
            raise ValueError("Issued MCU does not match outstanding plus settled MCU")
        expected_solvency = self.reconciliation_difference_mcu == 0
        if self.solvent_and_reconciled != expected_solvency:
            raise ValueError("Accounting solvency flag is inconsistent")
        expected_redemption = (
            self.settled_mcu/self.issued_mcu if self.issued_mcu else None
        )
        if self.redemption_rate != expected_redemption:
            raise ValueError("Accounting redemption rate is inconsistent")


@dataclass(frozen=True)
class CreditCirculationRunEvaluation:
    scenario_id: str
    upstream_scenario_id: str
    replication_index: int
    system: SystemEvaluation
    redistribution: RedistributionEvaluation
    user_proxy: UserProxyEvaluation
    accounting: AccountingEvaluation
    claim_scope: ClaimScope = ClaimScope.SCENARIO_CONDITIONAL
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    evaluation_version: str = CREDIT_SIMULATION_EVALUATION_VERSION

    def validate(self):
        if not self.scenario_id or not self.upstream_scenario_id:
            raise ValueError("Credit evaluation identity is incomplete")
        if self.replication_index < 0:
            raise ValueError("Credit evaluation replication cannot be negative")
        self.system.validate()
        self.redistribution.validate()
        self.user_proxy.validate()
        self.accounting.validate()
        if self.claim_scope is not ClaimScope.SCENARIO_CONDITIONAL:
            raise ValueError("Credit evaluation must remain scenario-conditional")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Credit evaluation must be simulated")


@dataclass(frozen=True)
class CreditCirculationGridEvaluation:
    evaluations: tuple[CreditCirculationRunEvaluation, ...]
    credit_simulation_grid_version: str
    upstream_evaluation_version: str
    evaluation_version: str = CREDIT_SIMULATION_EVALUATION_VERSION

    def validate(self, credit_result, upstream_evaluation):
        if len(self.evaluations) != len(credit_result.runs):
            raise ValueError("Every credit-grid run requires one evaluation")
        if self.credit_simulation_grid_version != credit_result.credit_simulation_grid_version:
            raise ValueError("Credit evaluation grid version is inconsistent")
        if self.upstream_evaluation_version != upstream_evaluation.evaluation_version:
            raise ValueError("Upstream evaluation version is inconsistent")
        for evaluation, run in zip(self.evaluations, credit_result.runs):
            evaluation.validate()
            if (evaluation.scenario_id != run.scenario.scenario_id
                    or evaluation.upstream_scenario_id
                    != run.scenario.upstream_scenario_id
                    or evaluation.replication_index
                    != run.upstream_replication_index):
                raise ValueError("Credit evaluation and run identity do not match")


def evaluate_credit_simulation_grid(
    credit_result: CreditSimulationGridResult,
    upstream_evaluation: SimulationGridEvaluation,
):
    """Evaluate all downstream runs without collapsing the four domains."""
    upstream_evaluation.grid.validate()
    credit_result.validate(len(upstream_evaluation.evaluations))
    scarcity_by_run = {}
    for item in upstream_evaluation.evaluations:
        item.validate()
        key = (item.scenario.scenario_id, item.replication_index)
        if key in scarcity_by_run:
            raise ValueError("Upstream scarcity evaluation identities must be unique")
        scarcity_by_run[key] = item
    evaluations = []
    for run in credit_result.runs:
        key = (run.scenario.upstream_scenario_id, run.upstream_replication_index)
        scarcity = scarcity_by_run.get(key)
        if scarcity is None:
            raise ValueError("Credit run lacks its upstream scarcity evaluation")
        evaluations.append(_evaluate_run(run, scarcity))
    result = CreditCirculationGridEvaluation(
        evaluations=tuple(evaluations),
        credit_simulation_grid_version=credit_result.credit_simulation_grid_version,
        upstream_evaluation_version=upstream_evaluation.evaluation_version,
    )
    result.validate(credit_result, upstream_evaluation)
    return result


def _evaluate_run(
    run: CreditPairedSimulationRun,
    scarcity: PairedScarcityEvaluation,
):
    run.validate()
    scarcity.validate()
    if run.candidate_count != scarcity.deferred_or_displaced_start_proxy_count:
        raise ValueError("Downstream candidates do not match the upstream start trade-off")
    changes = (
        scarcity.zero_availability_snapshot_share_change,
        scarcity.mean_availability_ratio_change,
        scarcity.mean_operational_scarcity_ratio_change,
    )
    system = SystemEvaluation(
        zero_availability_snapshot_share_change=changes[0],
        mean_availability_ratio_change=changes[1],
        mean_operational_scarcity_ratio_change=changes[2],
        additional_release_count=run.upstream_additional_release_count,
        deferred_or_displaced_start_proxy_count=(
            scarcity.deferred_or_displaced_start_proxy_count
        ),
        scarcity_metric_availability=(
            MetricAvailability.AVAILABLE
            if all(value is not None for value in changes)
            else MetricAvailability.NOT_EVALUABLE
        ),
    )
    residual_blocks = sum(
        "minimum_residual_receiver_capacity_violated" in item.blocking_reasons
        for item in run.safety_decisions
    )
    consumed = sum(value for _, _, value in run.ledger_snapshot.receiver_consumed)
    redistribution = RedistributionEvaluation(
        candidate_count=run.candidate_count,
        candidate_with_offer_count=run.offered_candidate_count,
        no_offer_candidate_count=run.candidate_count-run.offered_candidate_count,
        safety_pass_offer_count=run.safety_pass_offer_count,
        safety_block_offer_count=run.safety_block_offer_count,
        selected_receiver_count=run.selected_receiver_count,
        outside_unassigned_count=run.outside_unassigned_count,
        realized_redistribution_share=(
            run.selected_receiver_count/run.candidate_count
            if run.candidate_count else None
        ),
        outside_unassigned_share=(
            run.outside_unassigned_count/run.candidate_count
            if run.candidate_count else None
        ),
        receiver_capacity_consumed_count=consumed,
        residual_capacity_guard_block_count=residual_blocks,
        distributional_proxy_status=run.distributional_audit.status,
    )
    selected_ids = {
        item.selected_offer_id for item in run.choice_outcomes
        if item.outcome_type is ReceiverChoiceOutcomeType.RECEIVER_SELECTED
    }
    selected_offers = [item for item in run.offers if item.offer_id in selected_ids]
    distances = sorted(item.distance_km for item in run.offers)
    p95_index = max(0, math.ceil(.95*len(distances))-1) if distances else None
    user_proxy = UserProxyEvaluation(
        proposed_offer_count=len(run.offers),
        selected_offer_count=len(selected_offers),
        mean_proposed_credit_mcu=(
            fmean(item.amount_mcu for item in run.offers) if run.offers else None
        ),
        mean_selected_credit_mcu=(
            fmean(item.amount_mcu for item in selected_offers)
            if selected_offers else None
        ),
        mean_proposed_distance_km=fmean(distances) if distances else None,
        mean_selected_distance_km=(
            fmean(item.distance_km for item in selected_offers)
            if selected_offers else None
        ),
        p95_proposed_distance_km=(
            distances[p95_index] if p95_index is not None else None
        ),
        unresolved_warning_count=sum(
            len(item.unresolved_warnings) for item in run.offers
        ),
        total_session_cost_availability=MetricAvailability.NOT_EVALUABLE,
        travel_time_availability=MetricAvailability.NOT_EVALUABLE,
        welfare_availability=MetricAvailability.NOT_EVALUABLE,
        demographic_fairness_availability=MetricAvailability.NOT_EVALUABLE,
    )
    snapshot = run.ledger_snapshot
    issued_mcu = sum(item.amount_mcu for item in selected_offers)
    accounting = AccountingEvaluation(
        funded_mcu=snapshot.funded_mcu, available_mcu=snapshot.available_mcu,
        reserved_mcu=snapshot.reserved_mcu,
        outstanding_mcu=snapshot.outstanding_mcu,
        settled_mcu=snapshot.settled_mcu,
        reserve_target_mcu=snapshot.reserve_target_mcu,
        offerable_mcu=snapshot.offerable_mcu,
        proposed_offer_exposure_mcu=sum(item.amount_mcu for item in run.offers),
        issued_mcu=issued_mcu, issuance_count=run.issuance_count,
        reconciliation_difference_mcu=snapshot.reconciliation_difference_mcu,
        solvent_and_reconciled=(snapshot.reconciliation_difference_mcu == 0),
        redemption_rate=(snapshot.settled_mcu/issued_mcu if issued_mcu else None),
    )
    result = CreditCirculationRunEvaluation(
        scenario_id=run.scenario.scenario_id,
        upstream_scenario_id=run.scenario.upstream_scenario_id,
        replication_index=run.upstream_replication_index,
        system=system, redistribution=redistribution,
        user_proxy=user_proxy, accounting=accounting,
    )
    result.validate()
    return result
