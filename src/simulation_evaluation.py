"""Apply the canonical scarcity metrics to paired simulation projections."""

from dataclasses import dataclass
import math
from statistics import fmean

try:
    from .flow import SiteCapacitySnapshot
    from .scarcity import build_scarcity_snapshot_metrics
    from .simulation_contract import ClaimScope, ProvenanceClass
    from .simulation_grid import (
        PairedProjectionPoint,
        PairedSimulationRun,
        SimulationGridSpecification,
        SimulationGridResult,
        SimulationScenario,
    )
    from .trajectory import BaselineTrajectory
except ImportError:  # pragma: no cover
    from flow import SiteCapacitySnapshot
    from scarcity import build_scarcity_snapshot_metrics
    from simulation_contract import ClaimScope, ProvenanceClass
    from simulation_grid import (
        PairedProjectionPoint,
        PairedSimulationRun,
        SimulationGridSpecification,
        SimulationGridResult,
        SimulationScenario,
    )
    from trajectory import BaselineTrajectory


SIMULATION_EVALUATION_VERSION = "1.0.0"
DEFAULT_MINIMUM_COVERAGE = 0.8


@dataclass(frozen=True)
class ProjectedScarcitySummary:
    total_point_count: int
    eligible_point_count: int
    ineligible_point_count: int
    zero_availability_point_count: int
    zero_availability_snapshot_share: float | None
    mean_availability_ratio: float | None
    mean_operational_scarcity_ratio: float | None

    def validate(self):
        if self.total_point_count < 0:
            raise ValueError("Projected point count cannot be negative")
        if self.eligible_point_count + self.ineligible_point_count != self.total_point_count:
            raise ValueError("Projected eligibility counts are inconsistent")
        if not 0 <= self.zero_availability_point_count <= self.eligible_point_count:
            raise ValueError("Projected zero-availability count is inconsistent")
        ratios = (
            self.zero_availability_snapshot_share,
            self.mean_availability_ratio,
            self.mean_operational_scarcity_ratio,
        )
        if any(
            value is not None and (not math.isfinite(value) or not 0 <= value <= 1)
            for value in ratios
        ):
            raise ValueError("Projected scarcity ratios must be in [0, 1]")
        if self.eligible_point_count == 0 and any(value is not None for value in ratios):
            raise ValueError("Ineligible projections cannot have scarcity ratios")
        if self.eligible_point_count > 0:
            expected_share = (
                self.zero_availability_point_count / self.eligible_point_count
            )
            if not math.isclose(
                self.zero_availability_snapshot_share,
                expected_share,
                rel_tol=0,
                abs_tol=1e-12,
            ):
                raise ValueError("Projected zero-availability share is inconsistent")
            if not math.isclose(
                self.mean_availability_ratio
                + self.mean_operational_scarcity_ratio,
                1.0,
                rel_tol=0,
                abs_tol=1e-12,
            ):
                raise ValueError("Projected mean scarcity partition is inconsistent")


@dataclass(frozen=True)
class PairedScarcityEvaluation:
    scenario: SimulationScenario
    replication_index: int
    random_seed: int
    fixed: ProjectedScarcitySummary
    adaptive: ProjectedScarcitySummary
    zero_availability_snapshot_share_change: float | None
    mean_availability_ratio_change: float | None
    mean_operational_scarcity_ratio_change: float | None
    episode_metrics_applicable: bool = False
    claim_scope: ClaimScope = ClaimScope.SCENARIO_CONDITIONAL
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    evaluation_version: str = SIMULATION_EVALUATION_VERSION

    def validate(self):
        self.fixed.validate()
        self.adaptive.validate()
        if self.fixed.total_point_count != self.adaptive.total_point_count:
            raise ValueError("Paired arms must contain the same timestamps")
        if self.fixed.eligible_point_count != self.adaptive.eligible_point_count:
            raise ValueError("Paired arms must use the same eligibility mask")
        expected = (
            _difference(
                self.adaptive.zero_availability_snapshot_share,
                self.fixed.zero_availability_snapshot_share,
            ),
            _difference(
                self.adaptive.mean_availability_ratio,
                self.fixed.mean_availability_ratio,
            ),
            _difference(
                self.adaptive.mean_operational_scarcity_ratio,
                self.fixed.mean_operational_scarcity_ratio,
            ),
        )
        actual = (
            self.zero_availability_snapshot_share_change,
            self.mean_availability_ratio_change,
            self.mean_operational_scarcity_ratio_change,
        )
        if actual != expected:
            raise ValueError("Paired scarcity changes are inconsistent")
        if self.episode_metrics_applicable:
            raise ValueError("Episode metrics are invalid for one-step projections")
        if self.claim_scope is not ClaimScope.SCENARIO_CONDITIONAL:
            raise ValueError("Simulation evaluation must remain scenario-conditional")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Simulation evaluation must have simulated provenance")


@dataclass(frozen=True)
class SimulationGridEvaluation:
    grid: SimulationGridSpecification
    evaluations: tuple[PairedScarcityEvaluation, ...]
    simulation_grid_version: str
    baseline_generator_kind: str
    baseline_generator_version: str
    transition_model_version: str
    minimum_coverage_required: float
    evaluation_version: str = SIMULATION_EVALUATION_VERSION

    def validate(self, grid_result: SimulationGridResult):
        if self.grid != grid_result.grid:
            raise ValueError("Evaluation grid does not match the simulation grid")
        if len(self.evaluations) != len(grid_result.runs):
            raise ValueError("Every simulation run requires one scarcity evaluation")
        if not _valid_coverage_threshold(self.minimum_coverage_required):
            raise ValueError("Minimum coverage must be in [0, 1]")
        metadata = (
            self.simulation_grid_version == grid_result.simulation_grid_version,
            self.baseline_generator_kind == grid_result.baseline_generator_kind,
            self.baseline_generator_version == grid_result.baseline_generator_version,
            self.transition_model_version == grid_result.transition_model_version,
        )
        if not all(metadata):
            raise ValueError("Evaluation provenance does not match the simulation grid")
        for evaluation, run in zip(self.evaluations, grid_result.runs):
            evaluation.validate()
            if (evaluation.scenario != run.scenario
                    or evaluation.replication_index != run.replication_index
                    or evaluation.random_seed != run.random_seed):
                raise ValueError("Evaluation identity does not match its simulation run")


def evaluate_paired_run_scarcity(
    run: PairedSimulationRun,
    trajectory: BaselineTrajectory,
    *,
    minimum_coverage_required: float = DEFAULT_MINIMUM_COVERAGE,
):
    """Evaluate fixed/adaptive arms through the canonical scarcity summary."""
    run.validate()
    trajectory.validate()
    if not _valid_coverage_threshold(minimum_coverage_required):
        raise ValueError("Minimum coverage must be in [0, 1]")
    source_by_time = {
        point.trajectory_time_utc: point.source_state
        for point in trajectory.points
    }
    if len(source_by_time) != len(trajectory.points):
        raise ValueError("Trajectory timestamps must be unique")
    run_times = tuple(point.evaluation_time_utc for point in run.points)
    trajectory_times = tuple(point.trajectory_time_utc for point in trajectory.points)
    if run_times != trajectory_times:
        raise ValueError("Simulation run and trajectory timestamps do not match")

    fixed_snapshots = []
    adaptive_snapshots = []
    for point in run.points:
        source = source_by_time[point.evaluation_time_utc]
        if (point.source_available_count != source.available_evse_count
                or point.source_charging_count != source.charging_evse_count):
            raise ValueError("Simulation point does not match its source state")
        fixed_snapshots.append(_projection_snapshot(
            point, source, "fixed", minimum_coverage_required,
        ))
        adaptive_snapshots.append(_projection_snapshot(
            point, source, "adaptive", minimum_coverage_required,
        ))

    fixed = _snapshot_only_summary(fixed_snapshots)
    adaptive = _snapshot_only_summary(adaptive_snapshots)
    result = PairedScarcityEvaluation(
        scenario=run.scenario,
        replication_index=run.replication_index,
        random_seed=run.random_seed,
        fixed=fixed,
        adaptive=adaptive,
        zero_availability_snapshot_share_change=_difference(
            adaptive.zero_availability_snapshot_share,
            fixed.zero_availability_snapshot_share,
        ),
        mean_availability_ratio_change=_difference(
            adaptive.mean_availability_ratio,
            fixed.mean_availability_ratio,
        ),
        mean_operational_scarcity_ratio_change=_difference(
            adaptive.mean_operational_scarcity_ratio,
            fixed.mean_operational_scarcity_ratio,
        ),
    )
    result.validate()
    return result


def evaluate_simulation_grid_scarcity(
    grid_result: SimulationGridResult,
    trajectory: BaselineTrajectory,
    *,
    minimum_coverage_required: float = DEFAULT_MINIMUM_COVERAGE,
):
    """Evaluate every paired run without changing the scenario grid."""
    grid_result.validate()
    evaluations = tuple(
        evaluate_paired_run_scarcity(
            run, trajectory,
            minimum_coverage_required=minimum_coverage_required,
        )
        for run in grid_result.runs
    )
    result = SimulationGridEvaluation(
        grid=grid_result.grid,
        evaluations=evaluations,
        simulation_grid_version=grid_result.simulation_grid_version,
        baseline_generator_kind=grid_result.baseline_generator_kind,
        baseline_generator_version=grid_result.baseline_generator_version,
        transition_model_version=grid_result.transition_model_version,
        minimum_coverage_required=minimum_coverage_required,
    )
    result.validate(grid_result)
    return result


def _projection_snapshot(point, source, arm, minimum_coverage):
    if source.ocpi_location_key == "":
        raise ValueError("Projected scarcity requires a location key")
    if arm == "fixed":
        available = point.fixed_projected_available_count
        charging = point.fixed_projected_charging_count
    elif arm == "adaptive":
        available = point.adaptive_projected_available_count
        charging = point.adaptive_projected_charging_count
    else:  # pragma: no cover - internal guard
        raise ValueError("Projection arm must be fixed or adaptive")

    coverage = source.valid_observation_coverage
    evidence_eligible = (
        point.comparison_eligible
        and source.effective_operational_capacity > 0
        and coverage is not None
        and coverage >= minimum_coverage
    )
    if not point.comparison_eligible:
        available = source.available_evse_count
        charging = source.charging_evse_count
    effective = available + charging + source.reserved_evse_count
    return SiteCapacitySnapshot(
        collection_run_id=(
            f"simulation:{point.evaluation_time_utc.isoformat()}:{arm}"
        ),
        ocpi_location_key=source.ocpi_location_key,
        observation_time_utc=point.evaluation_time_utc,
        observed_evse_count=source.offered_evse_count,
        offered_evse_count=source.offered_evse_count,
        available_evse_count=available,
        charging_evse_count=charging,
        reserved_evse_count=source.reserved_evse_count,
        non_operational_evse_count=source.non_operational_evse_count,
        unknown_evse_count=source.indeterminate_evse_count,
        blocked_evse_count=0,
        unrecognized_status_evse_count=0,
        indeterminate_evse_count=source.indeterminate_evse_count,
        effective_operational_capacity=effective,
        occupancy_proxy=charging / effective if effective else None,
        availability_ratio=available / effective if effective else None,
        zero_availability=(available == 0 if evidence_eligible else None),
        valid_observation_coverage=coverage,
        minimum_coverage_required=minimum_coverage,
    )


def _snapshot_only_summary(snapshots):
    metrics = build_scarcity_snapshot_metrics(snapshots)
    eligible = [item for item in metrics if item.evidence_eligible]
    scarcity_values = [
        item.operational_scarcity_ratio for item in eligible
        if item.operational_scarcity_ratio is not None
    ]
    zero_count = sum(
        item.zero_availability_evidence is True for item in eligible
    )
    result = ProjectedScarcitySummary(
        total_point_count=len(metrics),
        eligible_point_count=len(eligible),
        ineligible_point_count=len(metrics) - len(eligible),
        zero_availability_point_count=zero_count,
        zero_availability_snapshot_share=(
            zero_count / len(eligible) if eligible else None
        ),
        mean_availability_ratio=(
            fmean(1 - value for value in scarcity_values)
            if scarcity_values else None
        ),
        mean_operational_scarcity_ratio=(
            fmean(scarcity_values) if scarcity_values else None
        ),
    )
    result.validate()
    return result


def _difference(adaptive, fixed):
    if adaptive is None or fixed is None:
        return None
    return adaptive - fixed


def _valid_coverage_threshold(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and 0 <= value <= 1
    )
