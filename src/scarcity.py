"""Observable capacity-scarcity evidence without inferring physical queues."""

from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import fmean
from typing import Iterable

try:
    from .flow import SiteCapacitySnapshot
except ImportError:  # Support direct execution from the src directory.
    from flow import SiteCapacitySnapshot


DEFAULT_EXPECTED_CADENCE_SECONDS = 5 * 60
DEFAULT_GAP_MULTIPLIER = 2.0


@dataclass(frozen=True)
class ScarcitySnapshotMetric:
    ocpi_location_key: str
    observation_time_utc: datetime
    evidence_eligible: bool
    operational_scarcity_ratio: float | None
    equipment_unavailability_ratio: float | None
    indeterminate_capacity_ratio: float | None
    zero_availability_evidence: bool | None
    available_evse_count: int
    effective_operational_capacity: int
    offered_evse_count: int

    def as_record(self):
        result = asdict(self)
        result["observation_time_utc"] = self.observation_time_utc.isoformat()
        return result


@dataclass(frozen=True)
class ZeroAvailabilityEpisode:
    ocpi_location_key: str
    episode_start_lower_utc: datetime | None
    episode_start_upper_utc: datetime
    episode_end_lower_utc: datetime
    episode_end_upper_utc: datetime | None
    duration_lower_minutes: float
    duration_upper_minutes: float | None
    duration_midpoint_minutes: float | None
    snapshot_count: int
    left_censored: bool
    right_censored: bool
    starts_after_collection_gap_or_ineligible: bool
    ends_before_collection_gap_or_ineligible: bool
    mean_effective_operational_capacity: float

    def as_record(self):
        result = asdict(self)
        for name in (
            "episode_start_lower_utc",
            "episode_start_upper_utc",
            "episode_end_lower_utc",
            "episode_end_upper_utc",
        ):
            value = result[name]
            result[name] = value.isoformat() if value is not None else None
        return result


@dataclass(frozen=True)
class SiteScarcitySummary:
    ocpi_location_key: str
    first_observation_utc: datetime
    last_observation_utc: datetime
    total_snapshot_count: int
    eligible_snapshot_count: int
    ineligible_snapshot_count: int
    zero_availability_snapshot_count: int
    zero_availability_snapshot_share: float | None
    zero_availability_episode_count: int
    complete_zero_availability_episode_count: int
    total_episode_duration_lower_minutes: float
    mean_availability_ratio: float | None
    mean_operational_scarcity_ratio: float | None
    mean_equipment_unavailability_ratio: float | None

    def as_record(self):
        result = asdict(self)
        result["first_observation_utc"] = self.first_observation_utc.isoformat()
        result["last_observation_utc"] = self.last_observation_utc.isoformat()
        return result


def build_scarcity_snapshot_metrics(
    snapshots: Iterable[SiteCapacitySnapshot],
):
    """Derive transparent scarcity and equipment-loss ratios per snapshot."""
    result = []
    for snapshot in snapshots:
        operational_scarcity = None
        if snapshot.availability_ratio is not None:
            operational_scarcity = 1 - snapshot.availability_ratio
        equipment_unavailability = None
        indeterminate_capacity = None
        if snapshot.offered_evse_count > 0:
            equipment_unavailability = (
                snapshot.non_operational_evse_count / snapshot.offered_evse_count
            )
            indeterminate_capacity = (
                snapshot.indeterminate_evse_count / snapshot.offered_evse_count
            )
        result.append(ScarcitySnapshotMetric(
            ocpi_location_key=snapshot.ocpi_location_key,
            observation_time_utc=snapshot.observation_time_utc,
            evidence_eligible=snapshot.zero_availability is not None,
            operational_scarcity_ratio=operational_scarcity,
            equipment_unavailability_ratio=equipment_unavailability,
            indeterminate_capacity_ratio=indeterminate_capacity,
            zero_availability_evidence=snapshot.zero_availability,
            available_evse_count=snapshot.available_evse_count,
            effective_operational_capacity=snapshot.effective_operational_capacity,
            offered_evse_count=snapshot.offered_evse_count,
        ))
    return result


def build_zero_availability_episodes(
    snapshots: Iterable[SiteCapacitySnapshot],
    *,
    expected_cadence_seconds: float = DEFAULT_EXPECTED_CADENCE_SECONDS,
    gap_multiplier: float = DEFAULT_GAP_MULTIPLIER,
):
    """Build interval-censored runs of quality-qualified zero availability."""
    if expected_cadence_seconds <= 0:
        raise ValueError("expected_cadence_seconds must be positive")
    if gap_multiplier <= 1:
        raise ValueError("gap_multiplier must be greater than one")
    gap_threshold = expected_cadence_seconds * gap_multiplier
    grouped = {}
    for snapshot in snapshots:
        grouped.setdefault(snapshot.ocpi_location_key, []).append(snapshot)

    episodes = []
    for location_key in sorted(grouped):
        ordered = sorted(
            grouped[location_key], key=lambda item: item.observation_time_utc
        )
        _validate_snapshot_times(ordered)
        index = 0
        while index < len(ordered):
            if ordered[index].zero_availability is not True:
                index += 1
                continue
            start_index = index
            while index + 1 < len(ordered):
                gap = (
                    ordered[index + 1].observation_time_utc
                    - ordered[index].observation_time_utc
                ).total_seconds()
                if gap > gap_threshold or ordered[index + 1].zero_availability is not True:
                    break
                index += 1
            end_index = index
            previous = ordered[start_index - 1] if start_index > 0 else None
            following = ordered[end_index + 1] if end_index + 1 < len(ordered) else None
            start_has_bound = _has_contiguous_false_before(
                previous, ordered[start_index], gap_threshold
            )
            end_has_bound = _has_contiguous_false_after(
                ordered[end_index], following, gap_threshold
            )
            start_lower = previous.observation_time_utc if start_has_bound else None
            end_upper = following.observation_time_utc if end_has_bound else None
            start_upper = ordered[start_index].observation_time_utc
            end_lower = ordered[end_index].observation_time_utc
            duration_lower = max(0.0, (end_lower - start_upper).total_seconds() / 60)
            duration_upper = None
            if start_lower is not None and end_upper is not None:
                duration_upper = (end_upper - start_lower).total_seconds() / 60
            duration_midpoint = (
                (duration_lower + duration_upper) / 2
                if duration_upper is not None
                else None
            )
            episode_snapshots = ordered[start_index:end_index + 1]
            episodes.append(ZeroAvailabilityEpisode(
                ocpi_location_key=location_key,
                episode_start_lower_utc=start_lower,
                episode_start_upper_utc=start_upper,
                episode_end_lower_utc=end_lower,
                episode_end_upper_utc=end_upper,
                duration_lower_minutes=duration_lower,
                duration_upper_minutes=duration_upper,
                duration_midpoint_minutes=duration_midpoint,
                snapshot_count=len(episode_snapshots),
                left_censored=start_lower is None,
                right_censored=end_upper is None,
                starts_after_collection_gap_or_ineligible=(
                    previous is not None and not start_has_bound
                ),
                ends_before_collection_gap_or_ineligible=(
                    following is not None and not end_has_bound
                ),
                mean_effective_operational_capacity=fmean(
                    item.effective_operational_capacity
                    for item in episode_snapshots
                ),
            ))
            index += 1
    return episodes


def summarize_site_scarcity(
    snapshots: Iterable[SiteCapacitySnapshot],
    episodes: Iterable[ZeroAvailabilityEpisode] | None = None,
):
    """Produce descriptive evidence summaries without interpreting a queue."""
    grouped = {}
    snapshot_list = list(snapshots)
    for snapshot in snapshot_list:
        grouped.setdefault(snapshot.ocpi_location_key, []).append(snapshot)
    episode_list = (
        list(episodes)
        if episodes is not None
        else build_zero_availability_episodes(snapshot_list)
    )
    episodes_by_location = {}
    for episode in episode_list:
        episodes_by_location.setdefault(episode.ocpi_location_key, []).append(episode)

    result = []
    for location_key in sorted(grouped):
        rows = sorted(grouped[location_key], key=lambda item: item.observation_time_utc)
        eligible = [item for item in rows if item.zero_availability is not None]
        zero_count = sum(item.zero_availability is True for item in eligible)
        location_episodes = episodes_by_location.get(location_key, [])
        availability_values = [
            item.availability_ratio
            for item in eligible
            if item.availability_ratio is not None
        ]
        operational_scarcity_values = [1 - item for item in availability_values]
        equipment_values = [
            item.non_operational_evse_count / item.offered_evse_count
            for item in rows
            if item.offered_evse_count > 0
        ]
        result.append(SiteScarcitySummary(
            ocpi_location_key=location_key,
            first_observation_utc=rows[0].observation_time_utc,
            last_observation_utc=rows[-1].observation_time_utc,
            total_snapshot_count=len(rows),
            eligible_snapshot_count=len(eligible),
            ineligible_snapshot_count=len(rows) - len(eligible),
            zero_availability_snapshot_count=zero_count,
            zero_availability_snapshot_share=(
                zero_count / len(eligible) if eligible else None
            ),
            zero_availability_episode_count=len(location_episodes),
            complete_zero_availability_episode_count=sum(
                not item.left_censored and not item.right_censored
                for item in location_episodes
            ),
            total_episode_duration_lower_minutes=sum(
                item.duration_lower_minutes for item in location_episodes
            ),
            mean_availability_ratio=(
                fmean(availability_values) if availability_values else None
            ),
            mean_operational_scarcity_ratio=(
                fmean(operational_scarcity_values)
                if operational_scarcity_values else None
            ),
            mean_equipment_unavailability_ratio=(
                fmean(equipment_values) if equipment_values else None
            ),
        ))
    return result


def _has_contiguous_false_before(previous, current, gap_threshold):
    if previous is None or current is None or previous.zero_availability is not False:
        return False
    return (
        current.observation_time_utc - previous.observation_time_utc
    ).total_seconds() <= gap_threshold


def _has_contiguous_false_after(current, following, gap_threshold):
    if current is None or following is None or following.zero_availability is not False:
        return False
    return (
        following.observation_time_utc - current.observation_time_utc
    ).total_seconds() <= gap_threshold


def _validate_snapshot_times(snapshots):
    for previous, current in zip(snapshots, snapshots[1:]):
        if current.observation_time_utc == previous.observation_time_utc:
            raise ValueError("Duplicate snapshot time for one location")
