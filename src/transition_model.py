"""Estimate observable EVSE state-transition hazards from bounded intervals."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

try:
    from .historical import EvseStateInterval
except ImportError:  # pragma: no cover
    from historical import EvseStateInterval


TRANSITION_MODEL_VERSION = "1.0.0"
CHANNELS = {
    "charging_start_proxy": ("available", "charging"),
    "release_proxy": ("charging", "available"),
}


@dataclass(frozen=True)
class TransitionHazardEstimate:
    channel: str
    source_status: str
    destination_status: str
    day_type: str
    local_hour: int | None
    exposure_hours: float
    event_count: int
    hazard_per_hour: float | None
    hazard_ci_lower: float | None
    hazard_ci_upper: float | None
    probability_per_decision_interval: float | None
    decision_interval_minutes: int
    locally_qualified: bool
    minimum_local_event_count: int
    estimator: str = "cause_specific_exponential_mle"
    uncertainty_method: str = "poisson_rate_score_95"

    def as_record(self):
        return asdict(self)


@dataclass(frozen=True)
class SiteTransitionModel:
    ocpi_location_key: str
    local_timezone: str
    training_start_utc: str
    training_end_utc: str
    included_interval_count: int
    excluded_interval_count: int
    estimates: tuple[TransitionHazardEstimate, ...]
    model_version: str = TRANSITION_MODEL_VERSION

    def as_record(self):
        result = asdict(self)
        result["estimates"] = [item.as_record() for item in self.estimates]
        return result

    def estimate_for(self, channel: str, at: datetime):
        """Return local stratum estimate, falling back to the site aggregate."""
        if channel not in CHANNELS:
            raise ValueError(f"Unsupported transition channel: {channel}")
        if at.tzinfo is None:
            raise ValueError("Transition lookup time must include a timezone")
        local = at.astimezone(ZoneInfo(self.local_timezone))
        day_type = "weekend" if local.weekday() >= 5 else "weekday"
        for estimate in self.estimates:
            if (estimate.channel == channel and estimate.day_type == day_type
                    and estimate.local_hour == local.hour
                    and estimate.locally_qualified):
                return estimate
        for estimate in self.estimates:
            if (estimate.channel == channel and estimate.day_type == "all"
                    and estimate.local_hour is None):
                return estimate
        raise ValueError(f"No estimate available for channel {channel}")


def estimate_baseline_transition_models(
    intervals: Iterable[EvseStateInterval],
    evse_to_location: Mapping[str, str],
    readiness_by_location: Mapping[str, object],
    *,
    local_timezone: str = "Europe/Vilnius",
    decision_interval_minutes: int = 5,
    minimum_local_event_count: int = 3,
):
    """Fit site hazards only where the formal transition readiness gate passes.

    Complete interval-censored runs are represented by midpoint bounds. The
    numerator is a bounded status-transition proxy; the denominator is exposure
    in its source status. Other exits are competing events, not target events.
    """
    if decision_interval_minutes <= 0:
        raise ValueError("decision_interval_minutes must be positive")
    if minimum_local_event_count < 1:
        raise ValueError("minimum_local_event_count must be positive")
    zone = ZoneInfo(local_timezone)
    grouped = {}
    for interval in intervals:
        location = evse_to_location.get(interval.ocpi_evse_key)
        if location is None:
            raise ValueError(f"Missing location for EVSE {interval.ocpi_evse_key}")
        grouped.setdefault(location, []).append(interval)

    models = []
    for location in sorted(grouped):
        readiness = readiness_by_location.get(location)
        if readiness is None:
            raise ValueError(f"Missing readiness assessment for location {location}")
        if not bool(getattr(readiness, "transition_model_ready", readiness)):
            raise ValueError(f"Location {location} is not transition-model ready")

        included = []
        excluded_count = 0
        for interval in grouped[location]:
            bounds = _representative_bounds(interval)
            if bounds is None:
                excluded_count += 1
            else:
                included.append((interval, *bounds))
        if not included:
            raise ValueError(f"Location {location} has no complete intervals")

        aggregate = {channel: [0.0, 0] for channel in CHANNELS}
        strata = {}
        for interval, start, end in included:
            for channel, (source, destination) in CHANNELS.items():
                if interval.status != source:
                    continue
                for day_type, hour, hours in _split_exposure(start, end, zone):
                    key = (channel, day_type, hour)
                    strata.setdefault(key, [0.0, 0])[0] += hours
                    aggregate[channel][0] += hours
                if interval.transition_to == destination:
                    # Attribute an exit to the source-risk stratum immediately
                    # before its midpoint event bound. This matters at an exact
                    # hour/day boundary.
                    event_local = (end - timedelta(microseconds=1)).astimezone(zone)
                    day_type = "weekend" if event_local.weekday() >= 5 else "weekday"
                    strata.setdefault((channel, day_type, event_local.hour), [0.0, 0])[1] += 1
                    aggregate[channel][1] += 1

        estimates = []
        for channel, (source, destination) in CHANNELS.items():
            exposure, events = aggregate[channel]
            estimates.append(_estimate(
                channel, source, destination, "all", None, exposure, events,
                decision_interval_minutes, minimum_local_event_count,
                aggregate=True,
            ))
            for day_type in ("weekday", "weekend"):
                for hour in range(24):
                    exposure, events = strata.get((channel, day_type, hour), (0.0, 0))
                    estimates.append(_estimate(
                        channel, source, destination, day_type, hour,
                        exposure, events, decision_interval_minutes,
                        minimum_local_event_count,
                    ))

        starts = [start for _, start, _ in included]
        ends = [end for _, _, end in included]
        models.append(SiteTransitionModel(
            ocpi_location_key=location,
            local_timezone=local_timezone,
            training_start_utc=min(starts).astimezone(timezone.utc).isoformat(),
            training_end_utc=max(ends).astimezone(timezone.utc).isoformat(),
            included_interval_count=len(included),
            excluded_interval_count=excluded_count,
            estimates=tuple(estimates),
        ))
    return models


def _representative_bounds(interval):
    if (interval.left_censored or interval.right_censored
            or interval.contains_collection_gap
            or interval.interval_start_lower_utc is None
            or interval.interval_end_upper_utc is None):
        return None
    start = _midpoint(interval.interval_start_lower_utc,
                      interval.interval_start_upper_utc)
    end = _midpoint(interval.interval_end_lower_utc,
                    interval.interval_end_upper_utc)
    if end <= start:
        return None
    return start, end


def _midpoint(left, right):
    return left + (right - left) / 2


def _split_exposure(start, end, zone):
    current = start.astimezone(timezone.utc)
    finish = end.astimezone(timezone.utc)
    while current < finish:
        next_hour = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        boundary = min(next_hour, finish)
        local = current.astimezone(zone)
        day_type = "weekend" if local.weekday() >= 5 else "weekday"
        yield day_type, local.hour, (boundary - current).total_seconds() / 3600
        current = boundary


def _estimate(channel, source, destination, day_type, local_hour,
              exposure_hours, event_count, decision_interval_minutes,
              minimum_local_event_count, aggregate=False):
    hazard = event_count / exposure_hours if exposure_hours > 0 else None
    ci_lower = ci_upper = None
    if exposure_hours > 0:
        z = 1.959963984540054
        center = event_count + z * z / 2
        margin = z * math.sqrt(event_count + z * z / 4)
        ci_lower = max(0.0, center - margin) / exposure_hours
        ci_upper = (center + margin) / exposure_hours
    probability = None
    if hazard is not None:
        probability = 1 - math.exp(-hazard * decision_interval_minutes / 60)
    return TransitionHazardEstimate(
        channel=channel,
        source_status=source,
        destination_status=destination,
        day_type=day_type,
        local_hour=local_hour,
        exposure_hours=exposure_hours,
        event_count=event_count,
        hazard_per_hour=hazard,
        hazard_ci_lower=ci_lower,
        hazard_ci_upper=ci_upper,
        probability_per_decision_interval=probability,
        decision_interval_minutes=decision_interval_minutes,
        locally_qualified=(
            exposure_hours > 0
            and (aggregate or event_count >= minimum_local_event_count)
        ),
        minimum_local_event_count=minimum_local_event_count,
    )
