"""Paired downstream grid for credit choice, safety and ledger outcomes."""

from dataclasses import dataclass, replace
import math
import random

try:
    from .fairness_safety import (
        DistributionalProxyAudit, FairnessSafetySpecification, GuardStatus,
        OfferSafetyDecision, audit_distributional_proxies, evaluate_offer_safety,
    )
    from .receiver_choice import (
        FundedReceiverOffer, ReceiverChoiceOutcome,
        ReceiverChoiceOutcomeType, ReceiverChoiceSpecification,
        draw_receiver_choice, evaluate_receiver_choice,
    )
    from .simulation_grid import (
        PairedSimulationRun, RedistributionCandidate, SimulationGridResult,
    )
    from .simulation_ledger import SimulationLedger, SimulationLedgerSnapshot
except ImportError:  # pragma: no cover
    from fairness_safety import (
        DistributionalProxyAudit, FairnessSafetySpecification, GuardStatus,
        OfferSafetyDecision, audit_distributional_proxies, evaluate_offer_safety,
    )
    from receiver_choice import (
        FundedReceiverOffer, ReceiverChoiceOutcome,
        ReceiverChoiceOutcomeType, ReceiverChoiceSpecification,
        draw_receiver_choice, evaluate_receiver_choice,
    )
    from simulation_grid import (
        PairedSimulationRun, RedistributionCandidate, SimulationGridResult,
    )
    from simulation_ledger import SimulationLedger, SimulationLedgerSnapshot


CREDIT_SIMULATION_GRID_VERSION = "1.0.0"


@dataclass(frozen=True)
class CreditSimulationGridSpecification:
    beta_credit_per_mcu_values: tuple[float, ...]
    beta_distance_per_km_values: tuple[float, ...]
    reserve_ratio_values: tuple[float, ...]
    minimum_residual_receiver_capacity_values: tuple[int, ...]
    opening_balance_mcu: int
    choice_random_seed: int

    def validate(self):
        numeric_axes = (
            ("credit sensitivity", self.beta_credit_per_mcu_values, None),
            ("distance sensitivity", self.beta_distance_per_km_values, None),
            ("reserve ratio", self.reserve_ratio_values, 1),
        )
        for name, values, upper in numeric_axes:
            if not values or len(values) != len(set(values)):
                raise ValueError(f"Grid {name} values must be non-empty and unique")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0
                or (upper is not None and value > upper)
                for value in values
            ):
                raise ValueError(f"Grid {name} values are invalid")
        residual = self.minimum_residual_receiver_capacity_values
        if (not residual or len(residual) != len(set(residual))
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or value < 0 for value in residual)):
            raise ValueError("Grid residual-capacity values are invalid")
        if (isinstance(self.opening_balance_mcu, bool)
                or not isinstance(self.opening_balance_mcu, int)
                or self.opening_balance_mcu < 0):
            raise ValueError("Grid opening balance must be non-negative integer MCU")
        if (isinstance(self.choice_random_seed, bool)
                or not isinstance(self.choice_random_seed, int)
                or self.choice_random_seed < 0):
            raise ValueError("Grid choice seed must be a non-negative integer")


@dataclass(frozen=True)
class CreditSimulationScenario:
    scenario_id: str
    upstream_scenario_id: str
    beta_credit_per_mcu: float
    beta_distance_per_km: float
    reserve_ratio: float
    minimum_residual_receiver_capacity: int


@dataclass(frozen=True)
class CreditPairedSimulationRun:
    scenario: CreditSimulationScenario
    upstream_replication_index: int
    upstream_random_seed: int
    choice_random_seed: int
    candidate_count: int
    offered_candidate_count: int
    proposed_offer_count: int
    safety_pass_offer_count: int
    safety_block_offer_count: int
    selected_receiver_count: int
    outside_unassigned_count: int
    reservation_success_count: int
    issuance_count: int
    candidates: tuple[RedistributionCandidate, ...]
    offers: tuple[FundedReceiverOffer, ...]
    safety_decisions: tuple[OfferSafetyDecision, ...]
    choice_outcomes: tuple[ReceiverChoiceOutcome, ...]
    distributional_audit: DistributionalProxyAudit
    ledger_snapshot: SimulationLedgerSnapshot
    common_random_numbers: bool = True

    def validate(self):
        counts = (
            self.upstream_replication_index, self.upstream_random_seed,
            self.choice_random_seed, self.candidate_count,
            self.offered_candidate_count, self.proposed_offer_count,
            self.safety_pass_offer_count, self.safety_block_offer_count,
            self.selected_receiver_count, self.outside_unassigned_count,
            self.reservation_success_count, self.issuance_count,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in counts):
            raise ValueError("Credit-grid counts and seeds must be non-negative")
        if self.candidate_count != len(self.candidates):
            raise ValueError("Credit-grid candidate count is inconsistent")
        if self.proposed_offer_count != len(self.offers):
            raise ValueError("Credit-grid offer count is inconsistent")
        if self.offered_candidate_count != len({item.candidate_id for item in self.offers}):
            raise ValueError("Credit-grid offered-candidate count is inconsistent")
        passed = sum(item.status is GuardStatus.PASS for item in self.safety_decisions)
        blocked = sum(item.status is GuardStatus.BLOCK for item in self.safety_decisions)
        if passed != self.safety_pass_offer_count or blocked != self.safety_block_offer_count:
            raise ValueError("Credit-grid safety totals are inconsistent")
        if len(self.safety_decisions) != len(self.offers):
            raise ValueError("Every proposed offer requires one safety decision")
        selected = sum(
            item.outcome_type is ReceiverChoiceOutcomeType.RECEIVER_SELECTED
            for item in self.choice_outcomes
        )
        outside = sum(
            item.outcome_type is ReceiverChoiceOutcomeType.OUTSIDE_UNASSIGNED
            for item in self.choice_outcomes
        )
        if (len(self.choice_outcomes) != self.candidate_count
                or selected != self.selected_receiver_count
                or outside != self.outside_unassigned_count
                or selected+outside != self.candidate_count):
            raise ValueError("Credit-grid choice outcomes do not reconcile")
        if not (self.issuance_count == self.reservation_success_count
                == self.selected_receiver_count):
            raise ValueError("Selected receivers must reconcile with reservations and issuance")
        self.distributional_audit.validate()
        self.ledger_snapshot.validate()
        if self.ledger_snapshot.reconciliation_difference_mcu != 0:
            raise ValueError("Credit-grid ledger does not reconcile")
        if not self.common_random_numbers:
            raise ValueError("Credit-grid MVP requires common random numbers")


@dataclass(frozen=True)
class CreditSimulationGridResult:
    grid: CreditSimulationGridSpecification
    upstream_simulation_grid_version: str
    runs: tuple[CreditPairedSimulationRun, ...]
    credit_simulation_grid_version: str = CREDIT_SIMULATION_GRID_VERSION

    def validate(self, upstream_run_count):
        self.grid.validate()
        downstream_scenarios = (
            len(self.grid.beta_credit_per_mcu_values)
            * len(self.grid.beta_distance_per_km_values)
            * len(self.grid.reserve_ratio_values)
            * len(self.grid.minimum_residual_receiver_capacity_values)
        )
        if len(self.runs) != upstream_run_count*downstream_scenarios:
            raise ValueError("Credit result does not cover the complete paired grid")
        for run in self.runs:
            run.validate()


def run_credit_simulation_grid(
    upstream: SimulationGridResult,
    grid: CreditSimulationGridSpecification,
    offers_by_candidate,
    receiver_capacities,
    *,
    fairness_template: FairnessSafetySpecification | None = None,
):
    """Extend upstream paired runs through choice, safety and ledger replay.

    `offers_by_candidate` contains immutable funded offers produced upstream by
    the future eligibility/allocation implementation. This runner never invents
    an alternative or modifies an observed trajectory.
    """
    upstream.validate()
    grid.validate()
    fairness_template = fairness_template or FairnessSafetySpecification()
    fairness_template.validate()
    offer_map = {key: tuple(value) for key, value in offers_by_candidate.items()}
    known_candidate_ids = {
        candidate.candidate_id
        for run in upstream.runs
        for candidate in run.redistribution_candidates
    }
    unknown_offer_keys = set(offer_map)-known_candidate_ids
    if unknown_offer_keys:
        raise ValueError("Funded offers reference candidates outside the upstream grid")
    capacity_map = dict(receiver_capacities)
    for key, value in capacity_map.items():
        if (not isinstance(key, tuple) or len(key) != 2
                or isinstance(value, bool) or not isinstance(value, int)
                or value < 0):
            raise ValueError("Receiver capacities require (site, time) and non-negative integers")
        site_id, at = key
        if not site_id or not hasattr(at, "tzinfo") or at.tzinfo is None:
            raise ValueError("Receiver capacity identity requires a site and timezone")

    results = []
    for upstream_run in upstream.runs:
        upstream_run.validate()
        for beta_credit in grid.beta_credit_per_mcu_values:
            for beta_distance in grid.beta_distance_per_km_values:
                for reserve_ratio in grid.reserve_ratio_values:
                    for residual in grid.minimum_residual_receiver_capacity_values:
                        scenario = _scenario(
                            upstream_run, beta_credit, beta_distance,
                            reserve_ratio, residual,
                        )
                        results.append(_run_downstream_scenario(
                            upstream_run, scenario, grid, offer_map, capacity_map,
                            replace(
                                fairness_template,
                                minimum_residual_receiver_capacity=residual,
                            ),
                        ))
    result = CreditSimulationGridResult(
        grid=grid,
        upstream_simulation_grid_version=upstream.simulation_grid_version,
        runs=tuple(results),
    )
    result.validate(len(upstream.runs))
    return result


def _scenario(run, beta_credit, beta_distance, reserve_ratio, residual):
    scenario_id = (
        f"{run.scenario.scenario_id}|beta_c={beta_credit}"
        f"|beta_d={beta_distance}|reserve={reserve_ratio}"
        f"|residual={residual}"
    )
    return CreditSimulationScenario(
        scenario_id=scenario_id,
        upstream_scenario_id=run.scenario.scenario_id,
        beta_credit_per_mcu=beta_credit,
        beta_distance_per_km=beta_distance,
        reserve_ratio=reserve_ratio,
        minimum_residual_receiver_capacity=residual,
    )


def _run_downstream_scenario(
    upstream_run: PairedSimulationRun,
    scenario,
    grid,
    offer_map,
    capacity_map,
    fairness_specification,
):
    candidates = sorted(
        upstream_run.redistribution_candidates,
        key=lambda item: (item.evaluation_time_utc, item.candidate_id),
    )
    opened_at = min(point.evaluation_time_utc for point in upstream_run.points)
    ledger = SimulationLedger(
        scenario_id=scenario.scenario_id,
        replication_index=upstream_run.replication_index,
        policy_id="matemafija-credit-circulation",
        policy_version=CREDIT_SIMULATION_GRID_VERSION,
        trajectory_id=scenario.upstream_scenario_id,
        random_seed=upstream_run.random_seed,
        reserve_ratio=scenario.reserve_ratio,
        opening_balance_mcu=grid.opening_balance_mcu,
        opened_at_utc=opened_at,
    )
    choice_seed = grid.choice_random_seed+upstream_run.replication_index
    rng = random.Random(choice_seed)
    downstream_candidates = []
    proposed_offers = []
    safety_decisions = []
    outcomes = []
    opened_capacity_keys = set()
    reservations = 0
    issuances = 0

    for base_candidate in candidates:
        candidate = replace(
            base_candidate,
            scenario_id=scenario.scenario_id,
            candidate_id=f"{base_candidate.candidate_id}|{scenario.scenario_id}",
        )
        candidate.validate()
        downstream_candidates.append(candidate)
        base_offers = offer_map.get(base_candidate.candidate_id, ())
        offers = tuple(
            replace(
                item,
                offer_id=f"{item.offer_id}|{scenario.scenario_id}",
                candidate_id=candidate.candidate_id,
                allocation_batch_id=(
                    f"{item.allocation_batch_id}|{scenario.scenario_id}"
                ),
            )
            for item in base_offers
        )
        for item in offers:
            item.validate(candidate)
            capacity_key = (item.receiver_site_id, candidate.evaluation_time_utc)
            if capacity_key not in opened_capacity_keys:
                capacity = capacity_map.get(capacity_key, 0)
                if capacity > 0:
                    ledger.open_receiver_capacity(
                        item.receiver_site_id, capacity,
                        at=candidate.evaluation_time_utc,
                    )
                opened_capacity_keys.add(capacity_key)
        proposed_offers.extend(offers)
        decisions = tuple(
            evaluate_offer_safety(
                candidate, item, ledger.snapshot, fairness_specification,
                evaluation_time_utc=candidate.evaluation_time_utc,
            )
            for item in offers
        )
        safety_decisions.extend(decisions)
        passing = tuple(
            item for item, decision in zip(offers, decisions)
            if decision.reservation_allowed
        )
        for item in passing:
            ledger.register_offer(item)
        choice = evaluate_receiver_choice(
            candidate, passing,
            ReceiverChoiceSpecification(
                beta_credit_per_mcu=scenario.beta_credit_per_mcu,
                beta_distance_per_km=scenario.beta_distance_per_km,
            ),
        )
        # Exactly one draw per candidate in every downstream scenario.
        outcome = draw_receiver_choice(choice, random_uniform=rng.random())
        outcomes.append(outcome)
        if outcome.outcome_type is ReceiverChoiceOutcomeType.OUTSIDE_UNASSIGNED:
            ledger.record_choice(outcome)
            selected_offer_id = None
        else:
            selected = next(
                item for item in passing if item.offer_id == outcome.selected_offer_id
            )
            attempt = ledger.record_choice(outcome, selected)
            if not attempt.success:
                raise ValueError("A safety-passed atomic reservation unexpectedly failed")
            reservations += 1
            ledger.complete_receiver_start(
                attempt.reservation_id, at=candidate.evaluation_time_utc,
            )
            issuances += 1
            selected_offer_id = selected.offer_id
        for item in passing:
            if item.offer_id != selected_offer_id:
                ledger.terminate_unselected_offer(
                    item.offer_id, at=candidate.evaluation_time_utc,
                    outcome="declined", reason_code="not_selected_by_choice_model",
                )

    audit = audit_distributional_proxies(
        total_candidate_count=len(downstream_candidates),
        offers=tuple(proposed_offers), outcomes=tuple(outcomes),
        safety_decisions=tuple(safety_decisions),
        specification=fairness_specification,
    )
    selected_count = sum(
        item.outcome_type is ReceiverChoiceOutcomeType.RECEIVER_SELECTED
        for item in outcomes
    )
    result = CreditPairedSimulationRun(
        scenario=scenario,
        upstream_replication_index=upstream_run.replication_index,
        upstream_random_seed=upstream_run.random_seed,
        choice_random_seed=choice_seed,
        candidate_count=len(downstream_candidates),
        offered_candidate_count=len({item.candidate_id for item in proposed_offers}),
        proposed_offer_count=len(proposed_offers),
        safety_pass_offer_count=sum(
            item.status is GuardStatus.PASS for item in safety_decisions
        ),
        safety_block_offer_count=sum(
            item.status is GuardStatus.BLOCK for item in safety_decisions
        ),
        selected_receiver_count=selected_count,
        outside_unassigned_count=len(outcomes)-selected_count,
        reservation_success_count=reservations,
        issuance_count=issuances,
        candidates=tuple(downstream_candidates), offers=tuple(proposed_offers),
        safety_decisions=tuple(safety_decisions),
        choice_outcomes=tuple(outcomes), distributional_audit=audit,
        ledger_snapshot=ledger.snapshot,
    )
    result.validate()
    return result
