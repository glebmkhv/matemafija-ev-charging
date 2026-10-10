"""Joint observable-scope robustness for credit-circulation scenarios."""

from dataclasses import dataclass
from enum import Enum
import math
from statistics import NormalDist, fmean

try:
    from .credit_simulation_evaluation import (
        CreditCirculationGridEvaluation, CreditCirculationRunEvaluation,
        MetricAvailability,
    )
    from .fairness_safety import GuardStatus
    from .robustness import RobustnessMetric
    from .simulation_contract import ClaimScope, ProvenanceClass
except ImportError:  # pragma: no cover
    from credit_simulation_evaluation import (
        CreditCirculationGridEvaluation, CreditCirculationRunEvaluation,
        MetricAvailability,
    )
    from fairness_safety import GuardStatus
    from robustness import RobustnessMetric
    from simulation_contract import ClaimScope, ProvenanceClass


CREDIT_ROBUSTNESS_VERSION = "1.0.0"


class JointRunStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    NOT_EVALUABLE = "not_evaluable"


@dataclass(frozen=True)
class JointRobustnessSpecification:
    primary_system_metric: RobustnessMetric = RobustnessMetric.ZERO_AVAILABILITY_SHARE
    minimum_system_effect_size: float = 0.0
    minimum_realized_redistribution_share: float = 0.0
    maximum_outside_unassigned_share: float = 1.0
    maximum_mean_selected_distance_km: float = 5.0
    require_distributional_proxy_pass: bool = True
    require_zero_residual_capacity_blocks: bool = True
    success_probability_threshold: float = 0.8
    maximum_not_evaluable_share: float = 0.2
    confidence_level: float = 0.95
    minimum_valid_replications: int = 20

    def validate(self):
        if not isinstance(self.primary_system_metric, RobustnessMetric):
            raise ValueError("Joint robustness system metric is invalid")
        for name, value in (
            ("minimum system effect", self.minimum_system_effect_size),
            ("maximum selected distance", self.maximum_mean_selected_distance_km),
        ):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative")
        for name, value, strict in (
            ("minimum redistribution share", self.minimum_realized_redistribution_share, False),
            ("maximum outside share", self.maximum_outside_unassigned_share, False),
            ("maximum not-evaluable share", self.maximum_not_evaluable_share, False),
            ("success probability", self.success_probability_threshold, True),
            ("confidence level", self.confidence_level, True),
        ):
            valid = 0 < value < 1 if strict else 0 <= value <= 1
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not valid:
                raise ValueError(f"{name} is invalid")
        if (not isinstance(self.require_distributional_proxy_pass, bool)
                or not isinstance(self.require_zero_residual_capacity_blocks, bool)):
            raise ValueError("Joint robustness gate flags must be boolean")
        if (isinstance(self.minimum_valid_replications, bool)
                or not isinstance(self.minimum_valid_replications, int)
                or self.minimum_valid_replications <= 0):
            raise ValueError("Minimum valid replications must be positive")


@dataclass(frozen=True)
class JointRunAssessment:
    scenario_id: str
    replication_index: int
    system_pass: bool | None
    redistribution_pass: bool | None
    user_proxy_pass: bool | None
    accounting_pass: bool
    status: JointRunStatus
    reason_codes: tuple[str, ...]
    system_metric_change: float | None

    def validate(self):
        if not self.scenario_id or self.replication_index < 0:
            raise ValueError("Joint run assessment identity is invalid")
        gates = (
            self.system_pass, self.redistribution_pass,
            self.user_proxy_pass, self.accounting_pass,
        )
        if any(value not in (True, False, None) for value in gates):
            raise ValueError("Joint run gate values are invalid")
        expected = (
            JointRunStatus.FAILURE if any(value is False for value in gates)
            else JointRunStatus.NOT_EVALUABLE if any(value is None for value in gates)
            else JointRunStatus.SUCCESS
        )
        if self.status is not expected:
            raise ValueError("Joint run status is inconsistent with domain gates")
        if self.status is JointRunStatus.SUCCESS and self.reason_codes:
            raise ValueError("Successful joint assessment cannot contain reasons")
        if self.status is not JointRunStatus.SUCCESS and not self.reason_codes:
            raise ValueError("Non-successful joint assessment requires reasons")
        if self.system_metric_change is not None and not math.isfinite(self.system_metric_change):
            raise ValueError("Joint system metric change must be finite")


@dataclass(frozen=True)
class JointScenarioRobustness:
    scenario_id: str
    total_replication_count: int
    valid_replication_count: int
    not_evaluable_replication_count: int
    not_evaluable_replication_share: float
    successful_replication_count: int
    failed_replication_count: int
    success_probability: float | None
    success_probability_ci_lower: float | None
    success_probability_ci_upper: float | None
    mean_system_metric_change: float | None
    observable_policy_robust: bool
    full_user_welfare_validated: bool = False
    demographic_fairness_validated: bool = False
    pilot_ready: bool = False

    def validate(self, specification):
        counts = (
            self.total_replication_count, self.valid_replication_count,
            self.not_evaluable_replication_count,
            self.successful_replication_count, self.failed_replication_count,
        )
        if any(value < 0 for value in counts) or self.total_replication_count <= 0:
            raise ValueError("Joint scenario counts are invalid")
        if self.valid_replication_count+self.not_evaluable_replication_count != self.total_replication_count:
            raise ValueError("Joint scenario evaluability counts do not reconcile")
        expected_missing_share = (
            self.not_evaluable_replication_count/self.total_replication_count
        )
        if not math.isclose(
            self.not_evaluable_replication_share, expected_missing_share,
            abs_tol=1e-12,
        ):
            raise ValueError("Joint not-evaluable share is inconsistent")
        if self.successful_replication_count+self.failed_replication_count != self.valid_replication_count:
            raise ValueError("Joint scenario outcome counts do not reconcile")
        if self.valid_replication_count == 0:
            if any(value is not None for value in (
                self.success_probability, self.success_probability_ci_lower,
                self.success_probability_ci_upper, self.mean_system_metric_change,
            )) or self.observable_policy_robust:
                raise ValueError("Non-evaluable scenario cannot contain robustness estimates")
        else:
            probability = self.successful_replication_count/self.valid_replication_count
            if not math.isclose(self.success_probability, probability, abs_tol=1e-12):
                raise ValueError("Joint success probability is inconsistent")
            if not (0 <= self.success_probability_ci_lower <= probability
                    <= self.success_probability_ci_upper <= 1):
                raise ValueError("Joint confidence interval is inconsistent")
            expected = (
                self.valid_replication_count >= specification.minimum_valid_replications
                and self.not_evaluable_replication_share
                <= specification.maximum_not_evaluable_share
                and self.success_probability_ci_lower
                >= specification.success_probability_threshold
            )
            if self.observable_policy_robust != expected:
                raise ValueError("Observable policy robustness is inconsistent")
        if (self.full_user_welfare_validated
                or self.demographic_fairness_validated or self.pilot_ready):
            raise ValueError("Current public-data model cannot claim full validation")


@dataclass(frozen=True)
class JointRobustnessResult:
    specification: JointRobustnessSpecification
    run_assessments: tuple[JointRunAssessment, ...]
    scenario_summaries: tuple[JointScenarioRobustness, ...]
    observable_robust_scenario_ids: tuple[str, ...]
    source_evaluation_version: str
    claim_scope: ClaimScope = ClaimScope.SCENARIO_CONDITIONAL
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    robustness_version: str = CREDIT_ROBUSTNESS_VERSION

    def validate(self):
        self.specification.validate()
        for item in self.run_assessments:
            item.validate()
        for item in self.scenario_summaries:
            item.validate(self.specification)
        expected = tuple(
            item.scenario_id for item in self.scenario_summaries
            if item.observable_policy_robust
        )
        if self.observable_robust_scenario_ids != expected:
            raise ValueError("Observable robust scenario IDs are inconsistent")
        if not self.source_evaluation_version:
            raise ValueError("Joint robustness source version is required")
        if self.claim_scope is not ClaimScope.SCENARIO_CONDITIONAL:
            raise ValueError("Joint robustness must remain scenario-conditional")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Joint robustness must be simulated")


def calculate_joint_policy_robustness(
    evaluation: CreditCirculationGridEvaluation,
    specification: JointRobustnessSpecification | None = None,
):
    specification = specification or JointRobustnessSpecification()
    specification.validate()
    assessments = tuple(
        _assess_run(item, specification) for item in evaluation.evaluations
    )
    grouped = {}
    for item in assessments:
        grouped.setdefault(item.scenario_id, []).append(item)
    summaries = []
    for scenario_id in sorted(grouped):
        rows = sorted(grouped[scenario_id], key=lambda item: item.replication_index)
        if len({item.replication_index for item in rows}) != len(rows):
            raise ValueError("Joint scenario contains duplicate replication indices")
        valid = [item for item in rows if item.status is not JointRunStatus.NOT_EVALUABLE]
        success_count = sum(item.status is JointRunStatus.SUCCESS for item in valid)
        failure_count = sum(item.status is JointRunStatus.FAILURE for item in valid)
        lower, upper = _wilson_interval(
            success_count, len(valid), specification.confidence_level,
        )
        system_changes = [
            item.system_metric_change for item in valid
            if item.system_metric_change is not None
        ]
        robust = (
            len(valid) >= specification.minimum_valid_replications
            and (len(rows)-len(valid))/len(rows)
            <= specification.maximum_not_evaluable_share
            and lower is not None
            and lower >= specification.success_probability_threshold
        )
        summary = JointScenarioRobustness(
            scenario_id=scenario_id,
            total_replication_count=len(rows),
            valid_replication_count=len(valid),
            not_evaluable_replication_count=len(rows)-len(valid),
            not_evaluable_replication_share=(len(rows)-len(valid))/len(rows),
            successful_replication_count=success_count,
            failed_replication_count=failure_count,
            success_probability=success_count/len(valid) if valid else None,
            success_probability_ci_lower=lower,
            success_probability_ci_upper=upper,
            mean_system_metric_change=(
                fmean(system_changes) if system_changes else None
            ),
            observable_policy_robust=robust,
        )
        summary.validate(specification)
        summaries.append(summary)
    result = JointRobustnessResult(
        specification=specification,
        run_assessments=assessments,
        scenario_summaries=tuple(summaries),
        observable_robust_scenario_ids=tuple(
            item.scenario_id for item in summaries
            if item.observable_policy_robust
        ),
        source_evaluation_version=evaluation.evaluation_version,
    )
    result.validate()
    return result


def _assess_run(item: CreditCirculationRunEvaluation, specification):
    item.validate()
    reasons = []
    change = _system_change(item, specification.primary_system_metric)
    if (item.system.scarcity_metric_availability
            is MetricAvailability.NOT_EVALUABLE or change is None):
        system_pass = None
        reasons.append("system_metric_not_evaluable")
    else:
        system_pass = _is_improvement(
            change, specification.primary_system_metric,
            specification.minimum_system_effect_size,
        )
        if not system_pass:
            reasons.append("system_improvement_gate_failed")

    redistribution = item.redistribution
    if (redistribution.realized_redistribution_share is None
            or redistribution.outside_unassigned_share is None
            or (specification.require_distributional_proxy_pass
                and redistribution.distributional_proxy_status
                is GuardStatus.NOT_EVALUABLE)):
        redistribution_pass = None
        reasons.append("redistribution_not_evaluable")
    else:
        redistribution_pass = (
            redistribution.realized_redistribution_share
            >= specification.minimum_realized_redistribution_share
            and redistribution.outside_unassigned_share
            <= specification.maximum_outside_unassigned_share
            and (not specification.require_distributional_proxy_pass
                 or redistribution.distributional_proxy_status is GuardStatus.PASS)
            and (not specification.require_zero_residual_capacity_blocks
                 or redistribution.residual_capacity_guard_block_count == 0)
        )
        if not redistribution_pass:
            reasons.append("redistribution_gate_failed")

    user = item.user_proxy
    if user.selected_offer_count == 0 or user.mean_selected_distance_km is None:
        user_pass = None
        reasons.append("user_proxy_not_evaluable")
    else:
        user_pass = (
            user.mean_selected_distance_km
            <= specification.maximum_mean_selected_distance_km
        )
        if not user_pass:
            reasons.append("user_proxy_gate_failed")

    accounting_pass = item.accounting.solvent_and_reconciled
    if not accounting_pass:
        reasons.append("accounting_gate_failed")
    gates = (system_pass, redistribution_pass, user_pass, accounting_pass)
    status = (
        JointRunStatus.FAILURE if any(value is False for value in gates)
        else JointRunStatus.NOT_EVALUABLE if any(value is None for value in gates)
        else JointRunStatus.SUCCESS
    )
    result = JointRunAssessment(
        scenario_id=item.scenario_id,
        replication_index=item.replication_index,
        system_pass=system_pass,
        redistribution_pass=redistribution_pass,
        user_proxy_pass=user_pass,
        accounting_pass=accounting_pass,
        status=status,
        reason_codes=tuple(sorted(set(reasons))),
        system_metric_change=change,
    )
    result.validate()
    return result


def _system_change(item, metric):
    if metric is RobustnessMetric.ZERO_AVAILABILITY_SHARE:
        return item.system.zero_availability_snapshot_share_change
    if metric is RobustnessMetric.MEAN_AVAILABILITY:
        return item.system.mean_availability_ratio_change
    if metric is RobustnessMetric.MEAN_OPERATIONAL_SCARCITY:
        return item.system.mean_operational_scarcity_ratio_change
    raise ValueError("Unsupported joint system metric")


def _is_improvement(change, metric, minimum):
    if metric is RobustnessMetric.MEAN_AVAILABILITY:
        return change > minimum
    return change < -minimum


def _wilson_interval(successes, trials, confidence_level):
    if trials == 0:
        return None, None
    z = NormalDist().inv_cdf(.5+confidence_level/2)
    probability = successes/trials
    denominator = 1+z*z/trials
    centre = (probability+z*z/(2*trials))/denominator
    half = z*math.sqrt(
        probability*(1-probability)/trials+z*z/(4*trials*trials)
    )/denominator
    lower = max(0.0, centre-half)
    upper = min(1.0, centre+half)
    # Keep the empirical proportion inside its Wilson interval even when libm
    # rounds a boundary endpoint one ulp inward on another operating system.
    return min(lower, probability), max(upper, probability)
