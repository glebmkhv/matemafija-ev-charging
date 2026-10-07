"""First uncertainty-aware statistics derived from observable site snapshots."""

from dataclasses import asdict, dataclass
from datetime import timedelta
import math
import random
from statistics import fmean
from typing import Iterable
from zoneinfo import ZoneInfo

try:
    from .flow import SiteCapacitySnapshot
    from .scarcity import ZeroAvailabilityEpisode, build_zero_availability_episodes
except ImportError:  # Support direct execution from the src directory.
    from flow import SiteCapacitySnapshot
    from scarcity import ZeroAvailabilityEpisode, build_zero_availability_episodes


DEFAULT_MINIMUM_HISTORY_DAYS = 7
DEFAULT_MINIMUM_LOCAL_DAYS = 7
DEFAULT_MINIMUM_EXPECTED_COVERAGE = 0.8
DEFAULT_EXPECTED_CADENCE_SECONDS = 5 * 60
DEFAULT_BOOTSTRAP_REPETITIONS = 1000
DEFAULT_MINIMUM_COMPLETE_EPISODES = 20


@dataclass(frozen=True)
class SiteDerivativeStatistics:
    ocpi_location_key: str
    history_start_utc: str
    history_end_utc: str
    history_span_days: float
    local_timezone: str
    local_day_count: int
    total_snapshot_count: int
    eligible_snapshot_count: int
    expected_snapshot_count: int
    eligible_expected_coverage: float
    statistically_qualified: bool
    qualification_reasons: tuple[str, ...]
    mean_availability_ratio: float | None
    mean_availability_ratio_ci_lower: float | None
    mean_availability_ratio_ci_upper: float | None
    mean_operational_scarcity_ratio: float | None
    mean_operational_scarcity_ratio_ci_lower: float | None
    mean_operational_scarcity_ratio_ci_upper: float | None
    zero_availability_snapshot_share: float | None
    zero_availability_snapshot_share_ci_lower: float | None
    zero_availability_snapshot_share_ci_upper: float | None
    mean_equipment_unavailability_ratio: float | None
    mean_equipment_unavailability_ratio_ci_lower: float | None
    mean_equipment_unavailability_ratio_ci_upper: float | None
    complete_zero_availability_episode_count: int
    p95_zero_availability_duration_minutes: float | None
    p95_zero_availability_duration_ci_lower: float | None
    p95_zero_availability_duration_ci_upper: float | None
    episode_duration_statistically_qualified: bool
    bootstrap_method: str
    bootstrap_repetitions: int
    confidence_level: float

    def as_record(self):
        result = asdict(self)
        result["qualification_reasons"] = list(self.qualification_reasons)
        return result


def estimate_site_derivative_statistics(
    snapshots: Iterable[SiteCapacitySnapshot],
    episodes: Iterable[ZeroAvailabilityEpisode] | None = None,
    *,
    local_timezone: str = "Europe/Vilnius",
    minimum_history_days: int = DEFAULT_MINIMUM_HISTORY_DAYS,
    minimum_local_days: int = DEFAULT_MINIMUM_LOCAL_DAYS,
    minimum_expected_coverage: float = DEFAULT_MINIMUM_EXPECTED_COVERAGE,
    expected_cadence_seconds: int = DEFAULT_EXPECTED_CADENCE_SECONDS,
    bootstrap_repetitions: int = DEFAULT_BOOTSTRAP_REPETITIONS,
    minimum_complete_episodes: int = DEFAULT_MINIMUM_COMPLETE_EPISODES,
    random_seed: int = 20261007,
):
    """Estimate site metrics; publish CIs only after qualification thresholds."""
    if minimum_history_days <= 0 or minimum_local_days <= 0:
        raise ValueError("minimum history and local-day thresholds must be positive")
    if not 0 < minimum_expected_coverage <= 1:
        raise ValueError("minimum_expected_coverage must be in (0, 1]")
    if expected_cadence_seconds <= 0:
        raise ValueError("expected_cadence_seconds must be positive")
    if bootstrap_repetitions < 100:
        raise ValueError("bootstrap_repetitions must be at least 100")
    if minimum_complete_episodes <= 0:
        raise ValueError("minimum_complete_episodes must be positive")

    snapshot_list = list(snapshots)
    episode_list = (
        list(episodes)
        if episodes is not None
        else build_zero_availability_episodes(snapshot_list)
    )
    grouped = {}
    for snapshot in snapshot_list:
        grouped.setdefault(snapshot.ocpi_location_key, []).append(snapshot)
    episodes_by_location = {}
    for episode in episode_list:
        episodes_by_location.setdefault(episode.ocpi_location_key, []).append(episode)

    zone = ZoneInfo(local_timezone)
    results = []
    for location_key in sorted(grouped):
        rows = sorted(grouped[location_key], key=lambda item: item.observation_time_utc)
        start = rows[0].observation_time_utc
        end = rows[-1].observation_time_utc
        span_seconds = max(0.0, (end - start).total_seconds())
        span_days = span_seconds / 86400
        expected_count = math.floor(span_seconds / expected_cadence_seconds) + 1
        eligible = [item for item in rows if item.zero_availability is not None]
        expected_coverage = min(1.0, len(eligible) / expected_count)
        local_days = sorted({
            item.observation_time_utc.astimezone(zone).date() for item in rows
        })
        reasons = []
        if span_days < minimum_history_days:
            reasons.append(
                f"history_span_below_{minimum_history_days}_days"
            )
        if len(local_days) < minimum_local_days:
            reasons.append(
                f"local_day_count_below_{minimum_local_days}"
            )
        if expected_coverage < minimum_expected_coverage:
            reasons.append(
                f"eligible_expected_coverage_below_{minimum_expected_coverage:.2f}"
            )
        qualified = not reasons

        availability = [
            item.availability_ratio
            for item in eligible if item.availability_ratio is not None
        ]
        scarcity = [1 - value for value in availability]
        zero = [float(item.zero_availability) for item in eligible]
        equipment = [
            item.non_operational_evse_count / item.offered_evse_count
            for item in rows if item.offered_evse_count > 0
        ]

        availability_ci = scarcity_ci = zero_ci = equipment_ci = (None, None)
        if qualified:
            availability_ci = _day_block_bootstrap_ci(
                eligible, zone, lambda item: item.availability_ratio,
                bootstrap_repetitions, random_seed + 1,
            )
            scarcity_ci = _day_block_bootstrap_ci(
                eligible, zone,
                lambda item: (
                    1 - item.availability_ratio
                    if item.availability_ratio is not None else None
                ),
                bootstrap_repetitions, random_seed + 2,
            )
            zero_ci = _day_block_bootstrap_ci(
                eligible, zone, lambda item: float(item.zero_availability),
                bootstrap_repetitions, random_seed + 3,
            )
            equipment_ci = _day_block_bootstrap_ci(
                rows, zone,
                lambda item: (
                    item.non_operational_evse_count / item.offered_evse_count
                    if item.offered_evse_count > 0 else None
                ),
                bootstrap_repetitions, random_seed + 4,
            )

        complete_episode_durations = [
            item.duration_midpoint_minutes
            for item in episodes_by_location.get(location_key, [])
            if not item.left_censored
            and not item.right_censored
            and item.duration_midpoint_minutes is not None
        ]
        episode_qualified = (
            qualified
            and len(complete_episode_durations) >= minimum_complete_episodes
        )
        p95_duration = (
            _quantile(complete_episode_durations, 0.95)
            if complete_episode_durations else None
        )
        duration_ci = (None, None)
        if episode_qualified:
            duration_ci = _iid_bootstrap_quantile_ci(
                complete_episode_durations, 0.95,
                bootstrap_repetitions, random_seed + 5,
            )

        results.append(SiteDerivativeStatistics(
            ocpi_location_key=location_key,
            history_start_utc=start.isoformat(),
            history_end_utc=end.isoformat(),
            history_span_days=span_days,
            local_timezone=local_timezone,
            local_day_count=len(local_days),
            total_snapshot_count=len(rows),
            eligible_snapshot_count=len(eligible),
            expected_snapshot_count=expected_count,
            eligible_expected_coverage=expected_coverage,
            statistically_qualified=qualified,
            qualification_reasons=tuple(reasons),
            mean_availability_ratio=_mean_or_none(availability),
            mean_availability_ratio_ci_lower=availability_ci[0],
            mean_availability_ratio_ci_upper=availability_ci[1],
            mean_operational_scarcity_ratio=_mean_or_none(scarcity),
            mean_operational_scarcity_ratio_ci_lower=scarcity_ci[0],
            mean_operational_scarcity_ratio_ci_upper=scarcity_ci[1],
            zero_availability_snapshot_share=_mean_or_none(zero),
            zero_availability_snapshot_share_ci_lower=zero_ci[0],
            zero_availability_snapshot_share_ci_upper=zero_ci[1],
            mean_equipment_unavailability_ratio=_mean_or_none(equipment),
            mean_equipment_unavailability_ratio_ci_lower=equipment_ci[0],
            mean_equipment_unavailability_ratio_ci_upper=equipment_ci[1],
            complete_zero_availability_episode_count=len(complete_episode_durations),
            p95_zero_availability_duration_minutes=p95_duration,
            p95_zero_availability_duration_ci_lower=duration_ci[0],
            p95_zero_availability_duration_ci_upper=duration_ci[1],
            episode_duration_statistically_qualified=episode_qualified,
            bootstrap_method="local-calendar-day block bootstrap",
            bootstrap_repetitions=bootstrap_repetitions,
            confidence_level=0.95,
        ))
    return results


def _day_block_bootstrap_ci(rows, zone, value_function, repetitions, seed):
    by_day = {}
    for row in rows:
        value = value_function(row)
        if value is None:
            continue
        day = row.observation_time_utc.astimezone(zone).date()
        by_day.setdefault(day, []).append(float(value))
    days = sorted(by_day)
    if len(days) < 2:
        return None, None
    generator = random.Random(seed)
    estimates = []
    for _ in range(repetitions):
        selected_days = [generator.choice(days) for _ in days]
        values = [value for day in selected_days for value in by_day[day]]
        estimates.append(fmean(values))
    return _quantile(estimates, 0.025), _quantile(estimates, 0.975)


def _iid_bootstrap_quantile_ci(values, probability, repetitions, seed):
    generator = random.Random(seed)
    estimates = []
    for _ in range(repetitions):
        sample = [generator.choice(values) for _ in values]
        estimates.append(_quantile(sample, probability))
    return _quantile(estimates, 0.025), _quantile(estimates, 0.975)


def _quantile(values, probability):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _mean_or_none(values):
    return fmean(values) if values else None
