"""Robustness regions and grid-identified release-response thresholds."""

from dataclasses import dataclass
from enum import Enum
import math
from statistics import NormalDist, fmean, median

try:
    from .simulation_contract import ClaimScope, ProvenanceClass
    from .simulation_evaluation import (
        PairedScarcityEvaluation,
        SimulationGridEvaluation,
    )
    from .simulation_grid import SimulationGridSpecification, SimulationScenario
except ImportError:  # pragma: no cover
    from simulation_contract import ClaimScope, ProvenanceClass
    from simulation_evaluation import (
        PairedScarcityEvaluation,
        SimulationGridEvaluation,
    )
    from simulation_grid import SimulationGridSpecification, SimulationScenario


ROBUSTNESS_VERSION = "1.0.0"


class RobustnessMetric(str, Enum):
    ZERO_AVAILABILITY_SHARE = "zero_availability_snapshot_share"
    MEAN_AVAILABILITY = "mean_availability_ratio"
    MEAN_OPERATIONAL_SCARCITY = "mean_operational_scarcity_ratio"


@dataclass(frozen=True)
class RobustnessSpecification:
    primary_metric: RobustnessMetric = RobustnessMetric.ZERO_AVAILABILITY_SHARE
    improvement_probability_threshold: float = 0.8
    minimum_effect_size: float = 0.0
    confidence_level: float = 0.95
    minimum_valid_replications: int = 20

    def validate(self):
        if not isinstance(self.primary_metric, RobustnessMetric):
            raise ValueError("Primary robustness metric is invalid")
        for name, value in (
            ("improvement probability", self.improvement_probability_threshold),
            ("confidence level", self.confidence_level),
        ):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 < value < 1):
                raise ValueError(f"{name} must be finite and in (0, 1)")
        if (isinstance(self.minimum_effect_size, bool)
                or not isinstance(self.minimum_effect_size, (int, float))
                or not math.isfinite(self.minimum_effect_size)
                or self.minimum_effect_size < 0):
            raise ValueError("Minimum effect size must be finite and non-negative")
        if (isinstance(self.minimum_valid_replications, bool)
                or not isinstance(self.minimum_valid_replications, int)
                or self.minimum_valid_replications <= 0):
            raise ValueError("Minimum valid replications must be positive")


@dataclass(frozen=True)
class ScenarioRobustnessSummary:
    scenario: SimulationScenario
    total_replication_count: int
    valid_replication_count: int
    missing_replication_count: int
    improvement_count: int
    improvement_probability: float | None
    improvement_probability_ci_lower: float | None
    improvement_probability_ci_upper: float | None
    mean_paired_change: float | None
    median_paired_change: float | None
    paired_change_interval_lower: float | None
    paired_change_interval_upper: float | None
    mean_deferred_or_displaced_start_proxy_count: float
    empirically_successful: bool
    robust_success: bool

    def validate(self, specification: RobustnessSpecification):
        if self.total_replication_count <= 0:
            raise ValueError("Scenario must contain replications")
        if (self.valid_replication_count + self.missing_replication_count
                != self.total_replication_count):
            raise ValueError("Scenario replication counts are inconsistent")
        if not 0 <= self.improvement_count <= self.valid_replication_count:
            raise ValueError("Improvement count is inconsistent")
        if (not math.isfinite(self.mean_deferred_or_displaced_start_proxy_count)
                or self.mean_deferred_or_displaced_start_proxy_count < 0):
            raise ValueError("Mean displaced start proxy must be non-negative")
        numeric = (
            self.improvement_probability,
            self.improvement_probability_ci_lower,
            self.improvement_probability_ci_upper,
            self.mean_paired_change,
            self.median_paired_change,
            self.paired_change_interval_lower,
            self.paired_change_interval_upper,
        )
        if self.valid_replication_count == 0:
            if any(value is not None for value in numeric):
                raise ValueError("Unavailable scenario cannot contain estimates")
            if self.empirically_successful or self.robust_success:
                raise ValueError("Unavailable scenario cannot be successful")
            return
        if any(value is None or not math.isfinite(value) for value in numeric):
            raise ValueError("Valid scenario requires finite estimates")
        if not (
            0 <= self.improvement_probability_ci_lower
            <= self.improvement_probability
            <= self.improvement_probability_ci_upper <= 1
        ):
            raise ValueError("Improvement probability interval is inconsistent")
        expected_probability = self.improvement_count / self.valid_replication_count
        if not math.isclose(
            self.improvement_probability, expected_probability,
            rel_tol=0, abs_tol=1e-12,
        ):
            raise ValueError("Improvement probability does not match its count")
        if not (
            self.paired_change_interval_lower
            <= self.median_paired_change
            <= self.paired_change_interval_upper
        ):
            raise ValueError("Paired change interval is inconsistent")
        expected_empirical = (
            self.improvement_probability
            >= specification.improvement_probability_threshold
        )
        expected_robust = (
            self.valid_replication_count >= specification.minimum_valid_replications
            and self.improvement_probability_ci_lower
            >= specification.improvement_probability_threshold
        )
        if self.empirically_successful != expected_empirical:
            raise ValueError("Empirical success classification is inconsistent")
        if self.robust_success != expected_robust:
            raise ValueError("Robust success classification is inconsistent")


@dataclass(frozen=True)
class MinimumResponseThreshold:
    price_intensity_lambda: float
    response_delay_minutes: int
    theta_arrival: float
    minimum_tested_theta_release: float | None
    identified_on_grid: bool
    supporting_scenario_id: str | None

    def validate(self):
        if (not math.isfinite(self.price_intensity_lambda)
                or not 0 <= self.price_intensity_lambda <= 1
                or isinstance(self.response_delay_minutes, bool)
                or not isinstance(self.response_delay_minutes, int)
                or self.response_delay_minutes < 0):
            raise ValueError("Threshold coordinates are invalid")
        if not math.isfinite(self.theta_arrival) or self.theta_arrival < 0:
            raise ValueError("Threshold arrival sensitivity is invalid")
        identified = self.minimum_tested_theta_release is not None
        if self.identified_on_grid != identified:
            raise ValueError("Threshold identification flag is inconsistent")
        if identified:
            if (not math.isfinite(self.minimum_tested_theta_release)
                    or self.minimum_tested_theta_release < 0
                    or not self.supporting_scenario_id):
                raise ValueError("Identified threshold requires theta and scenario")
        elif self.supporting_scenario_id is not None:
            raise ValueError("Unidentified threshold cannot cite a scenario")


@dataclass(frozen=True)
class RobustnessRegionResult:
    specification: RobustnessSpecification
    simulation_grid: SimulationGridSpecification
    scenario_summaries: tuple[ScenarioRobustnessSummary, ...]
    minimum_response_thresholds: tuple[MinimumResponseThreshold, ...]
    robust_scenario_ids: tuple[str, ...]
    evaluation_version: str
    simulation_grid_version: str
    baseline_generator_kind: str
    baseline_generator_version: str
    transition_model_version: str
    minimum_coverage_required: float
    claim_scope: ClaimScope = ClaimScope.SCENARIO_CONDITIONAL
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    robustness_version: str = ROBUSTNESS_VERSION

    def validate(self):
        self.specification.validate()
        self.simulation_grid.validate()
        if not all((
            self.evaluation_version,
            self.simulation_grid_version,
            self.baseline_generator_kind,
            self.baseline_generator_version,
            self.transition_model_version,
        )):
            raise ValueError("Robustness provenance metadata is incomplete")
        if (isinstance(self.minimum_coverage_required, bool)
                or not math.isfinite(self.minimum_coverage_required)
                or not 0 <= self.minimum_coverage_required <= 1):
            raise ValueError("Robustness coverage threshold is invalid")
        for summary in self.scenario_summaries:
            summary.validate(self.specification)
        expected_ids = tuple(
            item.scenario.scenario_id
            for item in self.scenario_summaries if item.robust_success
        )
        if self.robust_scenario_ids != expected_ids:
            raise ValueError("Robustness region IDs are inconsistent")
        for threshold in self.minimum_response_thresholds:
            threshold.validate()
        expected_coordinates = {
            (
                item.scenario.price_intensity_lambda,
                item.scenario.response_delay_minutes,
                item.scenario.theta_arrival,
            )
            for item in self.scenario_summaries
        }
        actual_coordinates = {
            (
                item.price_intensity_lambda,
                item.response_delay_minutes,
                item.theta_arrival,
            )
            for item in self.minimum_response_thresholds
        }
        if (actual_coordinates != expected_coordinates
                or len(actual_coordinates) != len(self.minimum_response_thresholds)):
            raise ValueError("Minimum thresholds do not cover each lambda/delay cell")
        for threshold in self.minimum_response_thresholds:
            candidates = [
                item for item in self.scenario_summaries
                if item.robust_success
                and item.scenario.price_intensity_lambda
                == threshold.price_intensity_lambda
                and item.scenario.response_delay_minutes
                == threshold.response_delay_minutes
                and item.scenario.theta_arrival == threshold.theta_arrival
            ]
            expected = min(
                candidates, key=lambda item: item.scenario.theta_release,
                default=None,
            )
            if expected is None:
                if threshold.identified_on_grid:
                    raise ValueError("Threshold is identified without a robust cell")
            elif (
                threshold.minimum_tested_theta_release
                != expected.scenario.theta_release
                or threshold.supporting_scenario_id != expected.scenario.scenario_id
            ):
                raise ValueError("Minimum tested threshold is not minimal")
        if self.claim_scope is not ClaimScope.SCENARIO_CONDITIONAL:
            raise ValueError("Robustness output must remain scenario-conditional")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Robustness output must have simulated provenance")


def calculate_robustness_region(
    grid_evaluation: SimulationGridEvaluation,
    specification: RobustnessSpecification | None = None,
):
    """Aggregate paired replications and identify conservative robust cells."""
    specification = specification or RobustnessSpecification()
    specification.validate()
    grid_evaluation.grid.validate()
    expected_evaluations = (
        len(grid_evaluation.grid.price_intensity_values)
        * len(grid_evaluation.grid.theta_release_values)
        * len(grid_evaluation.grid.theta_arrival_values)
        * len(grid_evaluation.grid.response_delay_minutes_values)
        * grid_evaluation.grid.replications
    )
    if len(grid_evaluation.evaluations) != expected_evaluations:
        raise ValueError("Evaluations do not cover the complete grid")
    grouped = {}
    for evaluation in grid_evaluation.evaluations:
        evaluation.validate()
        grouped.setdefault(evaluation.scenario, []).append(evaluation)

    expected_scenarios = (
        len(grid_evaluation.grid.price_intensity_values)
        * len(grid_evaluation.grid.theta_release_values)
        * len(grid_evaluation.grid.theta_arrival_values)
        * len(grid_evaluation.grid.response_delay_minutes_values)
    )
    if len(grouped) != expected_scenarios:
        raise ValueError("Evaluations do not cover the complete scenario grid")

    summaries = []
    for scenario in sorted(
        grouped,
        key=lambda item: (
            item.price_intensity_lambda,
            item.response_delay_minutes,
            item.theta_arrival,
            item.theta_release,
        ),
    ):
        rows = grouped[scenario]
        if len(rows) != grid_evaluation.grid.replications:
            raise ValueError("Scenario does not contain the declared replications")
        indices = {item.replication_index for item in rows}
        if indices != set(range(grid_evaluation.grid.replications)):
            raise ValueError("Scenario replication indices are incomplete")
        changes = [
            _metric_change(item, specification.primary_metric)
            for item in rows
        ]
        valid = [value for value in changes if value is not None]
        improvement_count = sum(
            _is_improvement(
                value,
                specification.primary_metric,
                specification.minimum_effect_size,
            )
            for value in valid
        )
        probability = improvement_count / len(valid) if valid else None
        ci_lower, ci_upper = _wilson_interval(
            improvement_count, len(valid), specification.confidence_level,
        )
        interval_alpha = (1 - specification.confidence_level) / 2
        summary = ScenarioRobustnessSummary(
            scenario=scenario,
            total_replication_count=len(rows),
            valid_replication_count=len(valid),
            missing_replication_count=len(rows) - len(valid),
            improvement_count=improvement_count,
            improvement_probability=probability,
            improvement_probability_ci_lower=ci_lower,
            improvement_probability_ci_upper=ci_upper,
            mean_paired_change=fmean(valid) if valid else None,
            median_paired_change=median(valid) if valid else None,
            paired_change_interval_lower=(
                _quantile(valid, interval_alpha) if valid else None
            ),
            paired_change_interval_upper=(
                _quantile(valid, 1 - interval_alpha) if valid else None
            ),
            mean_deferred_or_displaced_start_proxy_count=fmean(
                item.deferred_or_displaced_start_proxy_count for item in rows
            ),
            empirically_successful=(
                probability is not None
                and probability >= specification.improvement_probability_threshold
            ),
            robust_success=(
                len(valid) >= specification.minimum_valid_replications
                and ci_lower is not None
                and ci_lower >= specification.improvement_probability_threshold
            ),
        )
        summary.validate(specification)
        summaries.append(summary)

    thresholds = []
    for intensity in sorted(grid_evaluation.grid.price_intensity_values):
        for delay in sorted(grid_evaluation.grid.response_delay_minutes_values):
            for theta_arrival in sorted(grid_evaluation.grid.theta_arrival_values):
                candidates = [
                    item for item in summaries
                    if item.scenario.price_intensity_lambda == intensity
                    and item.scenario.response_delay_minutes == delay
                    and item.scenario.theta_arrival == theta_arrival
                    and item.robust_success
                ]
                supporting = min(
                    candidates, key=lambda item: item.scenario.theta_release,
                    default=None,
                )
                thresholds.append(MinimumResponseThreshold(
                    price_intensity_lambda=intensity,
                    response_delay_minutes=delay,
                    theta_arrival=theta_arrival,
                    minimum_tested_theta_release=(
                        supporting.scenario.theta_release if supporting else None
                    ),
                    identified_on_grid=supporting is not None,
                    supporting_scenario_id=(
                        supporting.scenario.scenario_id if supporting else None
                    ),
                ))

    result = RobustnessRegionResult(
        specification=specification,
        simulation_grid=grid_evaluation.grid,
        scenario_summaries=tuple(summaries),
        minimum_response_thresholds=tuple(thresholds),
        robust_scenario_ids=tuple(
            item.scenario.scenario_id for item in summaries if item.robust_success
        ),
        evaluation_version=grid_evaluation.evaluation_version,
        simulation_grid_version=grid_evaluation.simulation_grid_version,
        baseline_generator_kind=grid_evaluation.baseline_generator_kind,
        baseline_generator_version=grid_evaluation.baseline_generator_version,
        transition_model_version=grid_evaluation.transition_model_version,
        minimum_coverage_required=grid_evaluation.minimum_coverage_required,
    )
    result.validate()
    return result


def _metric_change(evaluation, metric):
    if metric is RobustnessMetric.ZERO_AVAILABILITY_SHARE:
        return evaluation.zero_availability_snapshot_share_change
    if metric is RobustnessMetric.MEAN_AVAILABILITY:
        return evaluation.mean_availability_ratio_change
    if metric is RobustnessMetric.MEAN_OPERATIONAL_SCARCITY:
        return evaluation.mean_operational_scarcity_ratio_change
    raise ValueError("Unsupported robustness metric")


def _is_improvement(change, metric, minimum_effect_size):
    if metric is RobustnessMetric.MEAN_AVAILABILITY:
        return change > minimum_effect_size
    return change < -minimum_effect_size


def _wilson_interval(successes, trials, confidence_level):
    if trials == 0:
        return None, None
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2)
    probability = successes / trials
    denominator = 1 + z * z / trials
    centre = (probability + z * z / (2 * trials)) / denominator
    half_width = (
        z
        * math.sqrt(
            probability * (1 - probability) / trials
            + z * z / (4 * trials * trials)
        )
        / denominator
    )
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def _quantile(values, probability):
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
