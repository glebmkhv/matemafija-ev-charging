"""Reconstruct bounded EVSE state intervals from successful OCPI snapshots."""

from dataclasses import asdict, dataclass
from datetime import datetime
import sqlite3
from typing import Iterable, Mapping


EXPECTED_CADENCE_SECONDS = 5 * 60
DEFAULT_GAP_MULTIPLIER = 2.0


@dataclass(frozen=True)
class StatusObservation:
    ocpi_evse_key: str
    observed_at: datetime
    status: str
    collection_run_id: str | None = None
    source_timestamp_quality: str | None = None


@dataclass(frozen=True)
class EvseStateInterval:
    ocpi_evse_key: str
    status: str
    interval_start_lower_utc: datetime | None
    interval_start_upper_utc: datetime
    interval_end_lower_utc: datetime
    interval_end_upper_utc: datetime | None
    duration_lower_minutes: float
    duration_upper_minutes: float | None
    duration_midpoint_minutes: float | None
    observation_count: int
    left_censored: bool
    right_censored: bool
    starts_after_collection_gap: bool
    ends_before_collection_gap: bool
    contains_collection_gap: bool
    transition_from: str | None
    transition_to: str | None
    available_to_charging_transition: bool
    charging_to_available_transition: bool

    def as_record(self):
        """Return a serialization-friendly dictionary with ISO UTC timestamps."""
        result = asdict(self)
        for name in (
            "interval_start_lower_utc",
            "interval_start_upper_utc",
            "interval_end_lower_utc",
            "interval_end_upper_utc",
        ):
            value = result[name]
            result[name] = value.isoformat() if value is not None else None
        return result


def _parse_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Observation timestamp must include a timezone: {value!r}")
    return parsed


def _observation(value):
    if isinstance(value, StatusObservation):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("Observations must be StatusObservation objects or mappings")
    evse_key = value.get("ocpi_evse_key")
    status = value.get("status_canonical", value.get("status"))
    if not evse_key or not status:
        raise ValueError("Every observation requires ocpi_evse_key and status")
    return StatusObservation(
        ocpi_evse_key=str(evse_key),
        observed_at=_parse_timestamp(value.get("observed_at")),
        status=str(status).strip().lower(),
        collection_run_id=value.get("collection_run_id"),
        source_timestamp_quality=value.get("source_timestamp_quality"),
    )


def load_ocpi_status_observations(
    connection: sqlite3.Connection,
    *,
    ocpi_evse_key: str | None = None,
    observed_from: str | None = None,
    observed_to: str | None = None,
):
    """Load observations from successful complete OCPI location snapshots."""
    conditions = [
        "r.run_status='success'",
        "r.is_complete_snapshot=1",
        "e.endpoint_type='ocpi_locations'",
    ]
    parameters = []
    if ocpi_evse_key is not None:
        conditions.append("o.ocpi_evse_key=?")
        parameters.append(ocpi_evse_key)
    if observed_from is not None:
        conditions.append("o.observed_at>=?")
        parameters.append(observed_from)
    if observed_to is not None:
        conditions.append("o.observed_at<?")
        parameters.append(observed_to)

    cursor = connection.execute(
        f"""SELECT o.collection_run_id, o.ocpi_evse_key, o.observed_at,
                   o.status_canonical, o.source_timestamp_quality
            FROM ocpi_evse_status_observations AS o
            JOIN collection_runs AS r USING (collection_run_id)
            JOIN source_endpoints AS e USING (source_endpoint_id)
            WHERE {' AND '.join(conditions)}
            ORDER BY o.ocpi_evse_key, o.observed_at, o.collection_run_id""",
        parameters,
    )
    column_names = [item[0] for item in cursor.description]
    return [
        _observation(dict(zip(column_names, row)))
        for row in cursor
    ]


def build_evse_state_intervals(
    observations: Iterable[StatusObservation | Mapping],
    *,
    expected_cadence_seconds: float = EXPECTED_CADENCE_SECONDS,
    gap_multiplier: float = DEFAULT_GAP_MULTIPLIER,
):
    """Build interval-censored state runs without bridging collection gaps."""
    if expected_cadence_seconds <= 0:
        raise ValueError("expected_cadence_seconds must be positive")
    if gap_multiplier <= 1:
        raise ValueError("gap_multiplier must be greater than one")
    gap_threshold = expected_cadence_seconds * gap_multiplier

    grouped = {}
    for raw_observation in observations:
        observation = _observation(raw_observation)
        grouped.setdefault(observation.ocpi_evse_key, []).append(observation)

    intervals = []
    for evse_key in sorted(grouped):
        ordered = sorted(
            grouped[evse_key],
            key=lambda item: (item.observed_at, item.collection_run_id or ""),
        )
        _validate_ordered_observations(ordered)
        segments = _split_at_collection_gaps(ordered, gap_threshold)
        for segment_index, segment in enumerate(segments):
            intervals.extend(
                _build_segment_intervals(
                    evse_key,
                    segment,
                    starts_after_gap=segment_index > 0,
                    ends_before_gap=segment_index < len(segments) - 1,
                )
            )
    return intervals


def _validate_ordered_observations(observations):
    for previous, current in zip(observations, observations[1:]):
        if current.observed_at == previous.observed_at:
            if current.status != previous.status:
                raise ValueError(
                    "Conflicting statuses for one EVSE at the same observation time"
                )
            raise ValueError("Duplicate observation time for one EVSE")


def _split_at_collection_gaps(observations, gap_threshold):
    if not observations:
        return []
    segments = [[observations[0]]]
    for previous, current in zip(observations, observations[1:]):
        gap_seconds = (current.observed_at - previous.observed_at).total_seconds()
        if gap_seconds > gap_threshold:
            segments.append([])
        segments[-1].append(current)
    return segments


def _build_segment_intervals(evse_key, observations, *, starts_after_gap, ends_before_gap):
    runs = []
    for observation in observations:
        if not runs or runs[-1][-1].status != observation.status:
            runs.append([observation])
        else:
            runs[-1].append(observation)

    result = []
    for index, run in enumerate(runs):
        previous_run = runs[index - 1] if index > 0 else None
        next_run = runs[index + 1] if index + 1 < len(runs) else None
        start_lower = previous_run[-1].observed_at if previous_run else None
        start_upper = run[0].observed_at
        end_lower = run[-1].observed_at
        end_upper = next_run[0].observed_at if next_run else None
        duration_lower = max(0.0, (end_lower - start_upper).total_seconds() / 60)
        duration_upper = None
        if start_lower is not None and end_upper is not None:
            duration_upper = (end_upper - start_lower).total_seconds() / 60
        duration_midpoint = (
            (duration_lower + duration_upper) / 2
            if duration_upper is not None
            else None
        )
        interval_starts_after_gap = starts_after_gap and index == 0
        interval_ends_before_gap = ends_before_gap and index == len(runs) - 1
        transition_from = previous_run[-1].status if previous_run else None
        transition_to = next_run[0].status if next_run else None
        result.append(
            EvseStateInterval(
                ocpi_evse_key=evse_key,
                status=run[0].status,
                interval_start_lower_utc=start_lower,
                interval_start_upper_utc=start_upper,
                interval_end_lower_utc=end_lower,
                interval_end_upper_utc=end_upper,
                duration_lower_minutes=duration_lower,
                duration_upper_minutes=duration_upper,
                duration_midpoint_minutes=duration_midpoint,
                observation_count=len(run),
                left_censored=previous_run is None,
                right_censored=next_run is None,
                starts_after_collection_gap=interval_starts_after_gap,
                ends_before_collection_gap=interval_ends_before_gap,
                contains_collection_gap=(
                    interval_starts_after_gap or interval_ends_before_gap
                ),
                transition_from=transition_from,
                transition_to=transition_to,
                available_to_charging_transition=(
                    transition_from == "available" and run[0].status == "charging"
                ),
                charging_to_available_transition=(
                    transition_from == "charging" and run[0].status == "available"
                ),
            )
        )
    return result
