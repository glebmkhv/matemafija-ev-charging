"""Observed-path and local-calendar-day block-bootstrap trajectories."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
import random
from typing import Iterable
from zoneinfo import ZoneInfo

try:
    from .simulation_contract import ObservedSystemState, ProvenanceClass
except ImportError:  # pragma: no cover
    from simulation_contract import ObservedSystemState, ProvenanceClass


TRAJECTORY_GENERATOR_VERSION = "1.0.0"


class TrajectoryGeneratorKind(str, Enum):
    OBSERVED_PATH = "observed_path"
    LOCAL_DAY_BLOCK_BOOTSTRAP = "local_day_block_bootstrap"


@dataclass(frozen=True)
class TrajectoryPoint:
    trajectory_time_utc: datetime
    source_observation_time_utc: datetime
    source_state: ObservedSystemState
    provenance: ProvenanceClass

    def validate(self):
        if (self.trajectory_time_utc.tzinfo is None
                or self.source_observation_time_utc.tzinfo is None):
            raise ValueError("Trajectory timestamps must include timezones")
        self.source_state.validate()
        if self.source_state.observation_time_utc != self.source_observation_time_utc:
            raise ValueError("Trajectory source timestamp is inconsistent")
        if self.provenance not in (
            ProvenanceClass.RECONSTRUCTED, ProvenanceClass.SIMULATED,
        ):
            raise ValueError("Trajectory provenance must be reconstructed or simulated")

    def as_record(self):
        source = asdict(self.source_state)
        source["observation_time_utc"] = self.source_state.observation_time_utc.isoformat()
        source["provenance"] = self.source_state.provenance.value
        return {
            "trajectory_time_utc": self.trajectory_time_utc.isoformat(),
            "source_observation_time_utc": self.source_observation_time_utc.isoformat(),
            "source_state": source,
            "provenance": self.provenance.value,
        }


@dataclass(frozen=True)
class SampledDayBlock:
    target_local_date: str
    source_local_date: str
    day_type: str
    point_count: int
    observation_coverage: float
    eligible_coverage: float


@dataclass(frozen=True)
class BaselineTrajectory:
    ocpi_location_key: str
    local_timezone: str
    generator_kind: TrajectoryGeneratorKind
    points: tuple[TrajectoryPoint, ...]
    sampled_blocks: tuple[SampledDayBlock, ...] = ()
    random_seed: int | None = None
    generator_version: str = TRAJECTORY_GENERATOR_VERSION

    def validate(self):
        ZoneInfo(self.local_timezone)
        if not self.ocpi_location_key or not self.points:
            raise ValueError("A trajectory requires a location and points")
        times = []
        for point in self.points:
            point.validate()
            if point.source_state.ocpi_location_key != self.ocpi_location_key:
                raise ValueError("Trajectory contains another location")
            times.append(point.trajectory_time_utc)
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValueError("Trajectory timestamps must be unique and ordered")
        if self.generator_kind is TrajectoryGeneratorKind.OBSERVED_PATH:
            if self.random_seed is not None or self.sampled_blocks:
                raise ValueError("Observed path cannot contain bootstrap metadata")
            if any(point.provenance is not ProvenanceClass.RECONSTRUCTED
                   or point.trajectory_time_utc != point.source_observation_time_utc
                   for point in self.points):
                raise ValueError("Observed path must retain reconstructed timestamps")
        else:
            if self.random_seed is None or self.random_seed < 0:
                raise ValueError("Bootstrap trajectory requires a non-negative seed")
            if not self.sampled_blocks:
                raise ValueError("Bootstrap trajectory requires sampled-block metadata")
            if any(point.provenance is not ProvenanceClass.SIMULATED
                   for point in self.points):
                raise ValueError("Bootstrap trajectory points must be simulated")


def generate_observed_path(
    states: Iterable[ObservedSystemState],
    *,
    local_timezone: str = "Europe/Vilnius",
):
    """Return an exact, deterministic replay path without changing timestamps."""
    rows = _validated_states(states)
    trajectory = BaselineTrajectory(
        ocpi_location_key=rows[0].ocpi_location_key,
        local_timezone=local_timezone,
        generator_kind=TrajectoryGeneratorKind.OBSERVED_PATH,
        points=tuple(TrajectoryPoint(
            trajectory_time_utc=row.observation_time_utc,
            source_observation_time_utc=row.observation_time_utc,
            source_state=row,
            provenance=ProvenanceClass.RECONSTRUCTED,
        ) for row in rows),
    )
    trajectory.validate()
    return trajectory


def generate_local_day_block_bootstrap(
    states: Iterable[ObservedSystemState],
    *,
    target_start_local_date: date,
    horizon_days: int,
    random_seed: int,
    readiness: object,
    local_timezone: str = "Europe/Vilnius",
    expected_cadence_seconds: int = 5 * 60,
    minimum_observation_coverage: float = 0.8,
    minimum_eligible_coverage: float = 0.8,
):
    """Resample complete local-day paths, stratified by weekday/weekend.

    Whole multivariate site snapshots are moved together. No component series is
    generated independently, so capacity partitions and within-day dependence
    remain exactly as observed in the selected source block.
    """
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative")
    if expected_cadence_seconds <= 0 or 86400 % expected_cadence_seconds:
        raise ValueError("expected cadence must be a positive divisor of 24 hours")
    for name, value in (
        ("minimum_observation_coverage", minimum_observation_coverage),
        ("minimum_eligible_coverage", minimum_eligible_coverage),
    ):
        if not 0 < value <= 1:
            raise ValueError(f"{name} must be in (0, 1]")
    if not bool(getattr(readiness, "historical_profile_ready", readiness)):
        raise ValueError("Block bootstrap requires historical_profile_ready")

    rows = _validated_states(states)
    zone = ZoneInfo(local_timezone)
    grouped = {}
    for row in rows:
        grouped.setdefault(row.observation_time_utc.astimezone(zone).date(), []).append(row)

    expected_count = 86400 // expected_cadence_seconds
    pools = {"weekday": [], "weekend": []}
    for source_date, block_rows in sorted(grouped.items()):
        if _local_day_seconds(source_date, zone) != 86400:
            continue
        observation_coverage = min(1.0, len(block_rows) / expected_count)
        eligible_count = sum(row.zero_availability_evidence is not None
                             for row in block_rows)
        eligible_coverage = min(1.0, eligible_count / expected_count)
        if (observation_coverage < minimum_observation_coverage
                or eligible_coverage < minimum_eligible_coverage):
            continue
        day_type = _day_type(source_date)
        pools[day_type].append((
            source_date,
            sorted(block_rows, key=lambda item: item.observation_time_utc),
            observation_coverage,
            eligible_coverage,
        ))

    target_dates = [target_start_local_date + timedelta(days=index)
                    for index in range(horizon_days)]
    required_types = {_day_type(item) for item in target_dates}
    missing = sorted(day_type for day_type in required_types if not pools[day_type])
    if missing:
        raise ValueError(f"No qualified source-day blocks for: {missing}")
    anomalous_targets = [str(item) for item in target_dates
                         if _local_day_seconds(item, zone) != 86400]
    if anomalous_targets:
        raise ValueError(
            "DST-transition target days require a dedicated block rule: "
            f"{anomalous_targets}"
        )

    rng = random.Random(random_seed)
    points = []
    sampled = []
    for target_date in target_dates:
        day_type = _day_type(target_date)
        source_date, block_rows, observation_coverage, eligible_coverage = rng.choice(
            pools[day_type]
        )
        for row in block_rows:
            source_local = row.observation_time_utc.astimezone(zone)
            naive_target = datetime.combine(target_date, source_local.timetz().replace(tzinfo=None))
            target_local = naive_target.replace(tzinfo=zone, fold=source_local.fold)
            target_utc = target_local.astimezone(timezone.utc)
            if target_utc.astimezone(zone).replace(tzinfo=None) != naive_target:
                raise ValueError("Cannot map a source point onto a DST-invalid local time")
            points.append(TrajectoryPoint(
                trajectory_time_utc=target_utc,
                source_observation_time_utc=row.observation_time_utc,
                source_state=row,
                provenance=ProvenanceClass.SIMULATED,
            ))
        sampled.append(SampledDayBlock(
            target_local_date=target_date.isoformat(),
            source_local_date=source_date.isoformat(),
            day_type=day_type,
            point_count=len(block_rows),
            observation_coverage=observation_coverage,
            eligible_coverage=eligible_coverage,
        ))

    trajectory = BaselineTrajectory(
        ocpi_location_key=rows[0].ocpi_location_key,
        local_timezone=local_timezone,
        generator_kind=TrajectoryGeneratorKind.LOCAL_DAY_BLOCK_BOOTSTRAP,
        points=tuple(sorted(points, key=lambda item: item.trajectory_time_utc)),
        sampled_blocks=tuple(sampled),
        random_seed=random_seed,
    )
    trajectory.validate()
    return trajectory


def _validated_states(states):
    rows = list(states)
    if not rows:
        raise ValueError("Source timeline cannot be empty")
    locations = set()
    times = []
    for row in rows:
        row.validate()
        locations.add(row.ocpi_location_key)
        times.append(row.observation_time_utc)
    if len(locations) != 1:
        raise ValueError("A trajectory generator accepts exactly one location")
    if times != sorted(times) or len(times) != len(set(times)):
        raise ValueError("Source timeline timestamps must be unique and ordered")
    return rows


def _day_type(value):
    return "weekend" if value.weekday() >= 5 else "weekday"


def _local_day_seconds(value, zone):
    start = datetime.combine(value, time.min, tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(value + timedelta(days=1), time.min,
                           tzinfo=zone).astimezone(timezone.utc)
    return int((end - start).total_seconds())
