"""Paired Monte Carlo grid for the release-only assumption-driven MVP."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
import math
import random

try:
    from .adaptive_policy import OsaDecision
    from .fixed_policy import ObservedTariff
    from .policy_integration import CompositionStatus, compose_adaptive_tariff
    from .release_response import apply_release_response, release_response_specification
    from .simulation_contract import PolicyAdoptionSpecification, ProvenanceClass
    from .trajectory import BaselineTrajectory
    from .transition_model import SiteTransitionModel
except ImportError:  # pragma: no cover
    from adaptive_policy import OsaDecision
    from fixed_policy import ObservedTariff
    from policy_integration import CompositionStatus, compose_adaptive_tariff
    from release_response import apply_release_response, release_response_specification
    from simulation_contract import PolicyAdoptionSpecification, ProvenanceClass
    from trajectory import BaselineTrajectory
    from transition_model import SiteTransitionModel


SIMULATION_GRID_VERSION = "1.0.0"


@dataclass(frozen=True)
class SimulationGridSpecification:
    price_intensity_values: tuple[float, ...]
    theta_release_values: tuple[float, ...]
    response_delay_minutes_values: tuple[int, ...]
    replications: int
    random_seed: int

    def validate(self):
        if not self.price_intensity_values or any(
            isinstance(value, bool) or not math.isfinite(value)
            or value < 0 or value > 1 for value in self.price_intensity_values
        ):
            raise ValueError("Grid lambda values must be non-empty and in [0, 1]")
        if not self.theta_release_values or any(
            isinstance(value, bool) or not math.isfinite(value) or value < 0
            for value in self.theta_release_values
        ):
            raise ValueError("Grid release sensitivities must be non-empty and non-negative")
        if not self.response_delay_minutes_values or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.response_delay_minutes_values
        ):
            raise ValueError("Grid delays must be non-empty and non-negative")
        if (isinstance(self.replications, bool)
                or not isinstance(self.replications, int)
                or isinstance(self.random_seed, bool)
                or not isinstance(self.random_seed, int)
                or self.replications <= 0 or self.random_seed < 0):
            raise ValueError("Replications must be positive and seed non-negative")
        for values in (
            self.price_intensity_values,
            self.theta_release_values,
            self.response_delay_minutes_values,
        ):
            if len(values) != len(set(values)):
                raise ValueError("Simulation grid values must be unique")


@dataclass(frozen=True)
class SimulationScenario:
    scenario_id: str
    price_intensity_lambda: float
    theta_release: float
    response_delay_minutes: int


@dataclass(frozen=True)
class PairedProjectionPoint:
    evaluation_time_utc: datetime
    source_available_count: int
    source_charging_count: int
    baseline_release_probability: float | None
    adaptive_release_probability: float | None
    fixed_release_count: int | None
    adaptive_release_count: int | None
    fixed_projected_available_count: int | None
    fixed_projected_charging_count: int | None
    adaptive_projected_available_count: int | None
    adaptive_projected_charging_count: int | None
    effective_policy_adjustment_eur_per_min: Decimal | None
    comparison_eligible: bool
    reason_code: str
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED

    def validate(self):
        if self.evaluation_time_utc.tzinfo is None:
            raise ValueError("Projection timestamp must include a timezone")
        if self.source_available_count < 0 or self.source_charging_count < 0:
            raise ValueError("Source counts cannot be negative")
        if self.comparison_eligible:
            probabilities = (
                self.baseline_release_probability,
                self.adaptive_release_probability,
            )
            if any(value is None or not 0 <= value <= 1 for value in probabilities):
                raise ValueError("Eligible projection requires bounded probabilities")
            counts = (
                self.fixed_release_count, self.adaptive_release_count,
                self.fixed_projected_available_count,
                self.fixed_projected_charging_count,
                self.adaptive_projected_available_count,
                self.adaptive_projected_charging_count,
            )
            if any(value is None or value < 0 for value in counts):
                raise ValueError("Eligible projection requires non-negative counts")
            if self.fixed_projected_available_count + self.fixed_projected_charging_count != (
                self.source_available_count + self.source_charging_count
            ):
                raise ValueError("Fixed projection violates operational capacity")
            if self.adaptive_projected_available_count + self.adaptive_projected_charging_count != (
                self.source_available_count + self.source_charging_count
            ):
                raise ValueError("Adaptive projection violates operational capacity")
        elif any(value is not None for value in (
            self.baseline_release_probability,
            self.adaptive_release_probability,
            self.fixed_release_count,
            self.adaptive_release_count,
            self.fixed_projected_available_count,
            self.fixed_projected_charging_count,
            self.adaptive_projected_available_count,
            self.adaptive_projected_charging_count,
            self.effective_policy_adjustment_eur_per_min,
        )):
            raise ValueError("Ineligible projection cannot contain simulated outcomes")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Monte Carlo projection must have simulated provenance")


@dataclass(frozen=True)
class PairedSimulationRun:
    scenario: SimulationScenario
    replication_index: int
    random_seed: int
    points: tuple[PairedProjectionPoint, ...]
    eligible_point_count: int
    withheld_point_count: int
    fixed_release_count: int
    adaptive_release_count: int
    additional_release_count: int
    common_random_numbers: bool = True

    def validate(self):
        if self.replication_index < 0 or self.random_seed < 0:
            raise ValueError("Replication metadata cannot be negative")
        for point in self.points:
            point.validate()
        eligible = [point for point in self.points if point.comparison_eligible]
        if len(eligible) != self.eligible_point_count:
            raise ValueError("Eligible projection count is inconsistent")
        if len(self.points) - len(eligible) != self.withheld_point_count:
            raise ValueError("Withheld projection count is inconsistent")
        fixed = sum(point.fixed_release_count for point in eligible)
        adaptive = sum(point.adaptive_release_count for point in eligible)
        if (fixed != self.fixed_release_count
                or adaptive != self.adaptive_release_count
                or adaptive - fixed != self.additional_release_count):
            raise ValueError("Paired release totals are inconsistent")
        if not self.common_random_numbers:
            raise ValueError("Paired MVP runs require common random numbers")


@dataclass(frozen=True)
class SimulationGridResult:
    grid: SimulationGridSpecification
    runs: tuple[PairedSimulationRun, ...]
    baseline_generator_kind: str
    baseline_generator_version: str
    transition_model_version: str
    simulation_grid_version: str = SIMULATION_GRID_VERSION

    def validate(self):
        self.grid.validate()
        expected = (
            len(self.grid.price_intensity_values)
            * len(self.grid.theta_release_values)
            * len(self.grid.response_delay_minutes_values)
            * self.grid.replications
        )
        if len(self.runs) != expected:
            raise ValueError("Simulation result does not cover the complete grid")
        for run in self.runs:
            run.validate()


def run_paired_simulation_grid(
    grid: SimulationGridSpecification,
    trajectory: BaselineTrajectory,
    transition_model: SiteTransitionModel,
    osa_decisions,
    f1_tariff: ObservedTariff,
    adoption_template: PolicyAdoptionSpecification,
    *,
    connector_key: str,
    entity_id: str,
):
    """Run one-step paired release projections over a scenario grid."""
    grid.validate()
    trajectory.validate()
    if transition_model.ocpi_location_key != trajectory.ocpi_location_key:
        raise ValueError("Transition model and trajectory belong to different sites")
    decision_rows = tuple(osa_decisions)
    decisions = {item.evaluation_time_utc: item for item in decision_rows}
    if len(decisions) != len(decision_rows):
        raise ValueError("OSA decisions must have unique timestamps")
    trajectory_times = {point.trajectory_time_utc for point in trajectory.points}
    if set(decisions) != trajectory_times:
        raise ValueError("OSA decisions must match every trajectory timestamp")

    scenarios = []
    for intensity in grid.price_intensity_values:
        for theta in grid.theta_release_values:
            for delay in grid.response_delay_minutes_values:
                scenarios.append(SimulationScenario(
                    scenario_id=f"lambda={intensity}|theta_r={theta}|tau={delay}",
                    price_intensity_lambda=intensity,
                    theta_release=theta,
                    response_delay_minutes=delay,
                ))

    runs = []
    for scenario in scenarios:
        adoption = replace(
            adoption_template,
            price_intensity_lambda=scenario.price_intensity_lambda,
        )
        compositions = []
        for point in trajectory.points:
            compositions.append(compose_adaptive_tariff(
                f1_tariff,
                decisions[point.trajectory_time_utc],
                adoption,
                connector_key=connector_key,
                entity_id=entity_id,
                evaluation_time_utc=point.trajectory_time_utc,
            ))
        driver_history = tuple(
            item.response_driver for item in compositions
            if item.response_driver is not None
        )
        composition_history = {
            point.trajectory_time_utc: composition
            for point, composition in zip(trajectory.points, compositions)
        }
        response_specification = release_response_specification(
            scenario.theta_release,
            delay_minutes=scenario.response_delay_minutes,
        )
        for replication_index in range(grid.replications):
            replication_seed = grid.random_seed + replication_index
            rng = random.Random(replication_seed)
            points = []
            for trajectory_point, composition in zip(trajectory.points, compositions):
                source = trajectory_point.source_state
                # Consume the same point-level innovations in every scenario,
                # including when this scenario later withholds the point.
                uniforms = [rng.random() for _ in range(source.charging_evse_count)]
                if composition.status is CompositionStatus.WITHHELD:
                    points.append(_withheld_point(
                        trajectory_point.trajectory_time_utc, source,
                        composition.reason_code,
                    ))
                    continue
                baseline = transition_model.estimate_for(
                    "release_proxy", trajectory_point.trajectory_time_utc
                )
                cutoff = trajectory_point.trajectory_time_utc - timedelta(
                    minutes=scenario.response_delay_minutes
                )
                eligible_driver_times = [
                    at for at in composition_history if at <= cutoff
                ]
                if not eligible_driver_times:
                    points.append(_withheld_point(
                        trajectory_point.trajectory_time_utc, source,
                        "delayed_driver_history_unavailable",
                    ))
                    continue
                delayed_composition = composition_history[max(eligible_driver_times)]
                if delayed_composition.response_driver is None:
                    points.append(_withheld_point(
                        trajectory_point.trajectory_time_utc, source,
                        "delayed_driver_withheld",
                    ))
                    continue
                try:
                    response = apply_release_response(
                        baseline,
                        driver_history,
                        response_specification,
                        entity_id=entity_id,
                        evaluation_time_utc=trajectory_point.trajectory_time_utc,
                    )
                except ValueError as error:
                    if "No response driver is available" not in str(error):
                        raise
                    points.append(_withheld_point(
                        trajectory_point.trajectory_time_utc, source,
                        "delayed_driver_history_unavailable",
                    ))
                    continue

                fixed_releases = sum(
                    value < response.baseline_release_probability for value in uniforms
                )
                adaptive_releases = sum(
                    value < response.adjusted_release_probability for value in uniforms
                )
                point = PairedProjectionPoint(
                    evaluation_time_utc=trajectory_point.trajectory_time_utc,
                    source_available_count=source.available_evse_count,
                    source_charging_count=source.charging_evse_count,
                    baseline_release_probability=response.baseline_release_probability,
                    adaptive_release_probability=response.adjusted_release_probability,
                    fixed_release_count=fixed_releases,
                    adaptive_release_count=adaptive_releases,
                    fixed_projected_available_count=(
                        source.available_evse_count + fixed_releases
                    ),
                    fixed_projected_charging_count=(
                        source.charging_evse_count - fixed_releases
                    ),
                    adaptive_projected_available_count=(
                        source.available_evse_count + adaptive_releases
                    ),
                    adaptive_projected_charging_count=(
                        source.charging_evse_count - adaptive_releases
                    ),
                    effective_policy_adjustment_eur_per_min=(
                        composition.effective_policy_adjustment_eur_per_min
                    ),
                    comparison_eligible=True,
                    reason_code="paired_projection_calculated",
                )
                point.validate()
                points.append(point)
            eligible = [point for point in points if point.comparison_eligible]
            fixed_total = sum(point.fixed_release_count for point in eligible)
            adaptive_total = sum(point.adaptive_release_count for point in eligible)
            run = PairedSimulationRun(
                scenario=scenario,
                replication_index=replication_index,
                random_seed=replication_seed,
                points=tuple(points),
                eligible_point_count=len(eligible),
                withheld_point_count=len(points)-len(eligible),
                fixed_release_count=fixed_total,
                adaptive_release_count=adaptive_total,
                additional_release_count=adaptive_total-fixed_total,
            )
            run.validate()
            runs.append(run)
    result = SimulationGridResult(
        grid=grid,
        runs=tuple(runs),
        baseline_generator_kind=trajectory.generator_kind.value,
        baseline_generator_version=trajectory.generator_version,
        transition_model_version=transition_model.model_version,
    )
    result.validate()
    return result


def _withheld_point(at, source, reason):
    point = PairedProjectionPoint(
        evaluation_time_utc=at,
        source_available_count=source.available_evse_count,
        source_charging_count=source.charging_evse_count,
        baseline_release_probability=None,
        adaptive_release_probability=None,
        fixed_release_count=None,
        adaptive_release_count=None,
        fixed_projected_available_count=None,
        fixed_projected_charging_count=None,
        adaptive_projected_available_count=None,
        adaptive_projected_charging_count=None,
        effective_policy_adjustment_eur_per_min=None,
        comparison_eligible=False,
        reason_code=reason,
    )
    point.validate()
    return point
