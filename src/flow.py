"""Build observable capacity and transition-flow time series from OCPI history."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Iterable, Mapping

try:
    from .historical import EvseStateInterval, _parse_timestamp
except ImportError:  # Support direct execution from the src directory.
    from historical import EvseStateInterval, _parse_timestamp


AVAILABLE_STATUSES = {"available"}
CHARGING_STATUSES = {"charging"}
RESERVED_STATUSES = {"reserved"}
NON_OPERATIONAL_STATUSES = {"outoforder", "inoperative"}
REMOVED_STATUSES = {"removed"}
INDETERMINATE_STATUSES = {"unknown", "blocked"}
CLASSIFIED_OFFERED_STATUSES = (
    AVAILABLE_STATUSES
    | CHARGING_STATUSES
    | RESERVED_STATUSES
    | NON_OPERATIONAL_STATUSES
)


@dataclass(frozen=True)
class SiteStatusObservation:
    collection_run_id: str
    ocpi_location_key: str
    ocpi_evse_key: str
    observed_at: datetime
    status: str


@dataclass(frozen=True)
class SiteCapacitySnapshot:
    collection_run_id: str
    ocpi_location_key: str
    observation_time_utc: datetime
    observed_evse_count: int
    offered_evse_count: int
    available_evse_count: int
    charging_evse_count: int
    reserved_evse_count: int
    non_operational_evse_count: int
    unknown_evse_count: int
    blocked_evse_count: int
    unrecognized_status_evse_count: int
    indeterminate_evse_count: int
    effective_operational_capacity: int
    occupancy_proxy: float | None
    availability_ratio: float | None
    zero_availability: bool | None
    valid_observation_coverage: float | None
    minimum_coverage_required: float

    def as_record(self):
        result = asdict(self)
        result["observation_time_utc"] = self.observation_time_utc.isoformat()
        return result


@dataclass(frozen=True)
class TransitionFlowBin:
    ocpi_location_key: str
    bin_start_utc: datetime
    bin_end_utc: datetime
    bin_width_minutes: int
    charging_start_proxy_count: int
    release_proxy_count: int
    event_time_assignment: str = "transition_upper_bound"

    def as_record(self):
        result = asdict(self)
        result["bin_start_utc"] = self.bin_start_utc.isoformat()
        result["bin_end_utc"] = self.bin_end_utc.isoformat()
        return result


def load_ocpi_site_status_observations(
    connection: sqlite3.Connection,
    *,
    ocpi_location_key: str | None = None,
    observed_from: str | None = None,
    observed_to: str | None = None,
):
    """Load EVSE statuses with their OCPI location from complete snapshots."""
    conditions = [
        "r.run_status='success'",
        "r.is_complete_snapshot=1",
        "e.endpoint_type='ocpi_locations'",
    ]
    parameters = []
    if ocpi_location_key is not None:
        conditions.append("v.ocpi_location_key=?")
        parameters.append(ocpi_location_key)
    if observed_from is not None:
        conditions.append("o.observed_at>=?")
        parameters.append(observed_from)
    if observed_to is not None:
        conditions.append("o.observed_at<?")
        parameters.append(observed_to)

    cursor = connection.execute(
        f"""SELECT o.collection_run_id, v.ocpi_location_key,
                   o.ocpi_evse_key, o.observed_at, o.status_canonical
            FROM ocpi_evse_status_observations AS o
            JOIN ocpi_evses AS v USING (ocpi_evse_key)
            JOIN collection_runs AS r USING (collection_run_id)
            JOIN source_endpoints AS e USING (source_endpoint_id)
            WHERE {' AND '.join(conditions)}
            ORDER BY o.observed_at, v.ocpi_location_key, o.ocpi_evse_key""",
        parameters,
    )
    column_names = [item[0] for item in cursor.description]
    return [_site_observation(dict(zip(column_names, row))) for row in cursor]


def load_evse_location_map(connection: sqlite3.Connection):
    """Return the source-native EVSE-to-location relationship."""
    return dict(connection.execute(
        "SELECT ocpi_evse_key, ocpi_location_key FROM ocpi_evses"
    ))


def _site_observation(value):
    if isinstance(value, SiteStatusObservation):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("Site observations must be objects or mappings")
    status = value.get("status_canonical", value.get("status"))
    required = (
        value.get("collection_run_id"),
        value.get("ocpi_location_key"),
        value.get("ocpi_evse_key"),
        status,
    )
    if any(item in (None, "") for item in required):
        raise ValueError("Site observation is missing an identity or status")
    return SiteStatusObservation(
        collection_run_id=str(value["collection_run_id"]),
        ocpi_location_key=str(value["ocpi_location_key"]),
        ocpi_evse_key=str(value["ocpi_evse_key"]),
        observed_at=_parse_timestamp(value.get("observed_at")),
        status=str(status).strip().lower(),
    )


def build_site_capacity_snapshots(
    observations: Iterable[SiteStatusObservation | Mapping],
    *,
    minimum_coverage: float = 0.8,
):
    """Aggregate source-native EVSE states into location capacity snapshots."""
    if not 0 <= minimum_coverage <= 1:
        raise ValueError("minimum_coverage must be between zero and one")
    grouped = {}
    for raw_observation in observations:
        observation = _site_observation(raw_observation)
        key = (
            observation.collection_run_id,
            observation.ocpi_location_key,
            observation.observed_at,
        )
        grouped.setdefault(key, []).append(observation)

    result = []
    for (run_id, location_key, observed_at), rows in sorted(
        grouped.items(), key=lambda item: (item[0][2], item[0][1], item[0][0])
    ):
        evse_keys = [row.ocpi_evse_key for row in rows]
        if len(evse_keys) != len(set(evse_keys)):
            raise ValueError("Duplicate EVSE within one location snapshot")
        statuses = [row.status for row in rows]
        observed_count = len(statuses)
        offered_statuses = [
            status for status in statuses if status not in REMOVED_STATUSES
        ]
        offered_count = len(offered_statuses)
        available_count = sum(status in AVAILABLE_STATUSES for status in statuses)
        charging_count = sum(status in CHARGING_STATUSES for status in statuses)
        reserved_count = sum(status in RESERVED_STATUSES for status in statuses)
        non_operational_count = sum(
            status in NON_OPERATIONAL_STATUSES for status in statuses
        )
        unknown_count = sum(status == "unknown" for status in statuses)
        blocked_count = sum(status == "blocked" for status in statuses)
        recognized_statuses = (
            CLASSIFIED_OFFERED_STATUSES
            | REMOVED_STATUSES
            | INDETERMINATE_STATUSES
        )
        unrecognized_count = sum(
            status not in recognized_statuses for status in statuses
        )
        indeterminate_count = unknown_count + blocked_count + unrecognized_count
        effective_capacity = available_count + charging_count + reserved_count
        classified_offered_count = sum(
            status in CLASSIFIED_OFFERED_STATUSES for status in offered_statuses
        )
        coverage = (
            classified_offered_count / offered_count if offered_count else None
        )
        occupancy_proxy = (
            charging_count / effective_capacity if effective_capacity else None
        )
        availability_ratio = (
            available_count / effective_capacity if effective_capacity else None
        )
        zero_availability = None
        if (
            effective_capacity > 0
            and coverage is not None
            and coverage >= minimum_coverage
        ):
            zero_availability = available_count == 0
        result.append(SiteCapacitySnapshot(
            collection_run_id=run_id,
            ocpi_location_key=location_key,
            observation_time_utc=observed_at,
            observed_evse_count=observed_count,
            offered_evse_count=offered_count,
            available_evse_count=available_count,
            charging_evse_count=charging_count,
            reserved_evse_count=reserved_count,
            non_operational_evse_count=non_operational_count,
            unknown_evse_count=unknown_count,
            blocked_evse_count=blocked_count,
            unrecognized_status_evse_count=unrecognized_count,
            indeterminate_evse_count=indeterminate_count,
            effective_operational_capacity=effective_capacity,
            occupancy_proxy=occupancy_proxy,
            availability_ratio=availability_ratio,
            zero_availability=zero_availability,
            valid_observation_coverage=coverage,
            minimum_coverage_required=minimum_coverage,
        ))
    return result


def build_transition_flow_bins(
    intervals: Iterable[EvseStateInterval],
    evse_to_location: Mapping[str, str],
    *,
    bin_width_minutes: int = 15,
):
    """Count bounded transition proxies in complete UTC bins per location."""
    if bin_width_minutes <= 0 or 1440 % bin_width_minutes:
        raise ValueError("bin_width_minutes must be a positive divisor of 1440")
    by_location = {}
    for interval in intervals:
        location_key = evse_to_location.get(interval.ocpi_evse_key)
        if location_key is None:
            raise ValueError(f"Missing location for EVSE {interval.ocpi_evse_key}")
        by_location.setdefault(location_key, []).append(interval)

    result = []
    for location_key in sorted(by_location):
        location_intervals = by_location[location_key]
        observed_times = [
            time
            for interval in location_intervals
            for time in (
                interval.interval_start_upper_utc,
                interval.interval_end_lower_utc,
            )
        ]
        if not observed_times:
            continue
        first_bin = _floor_utc_bin(min(observed_times), bin_width_minutes)
        last_bin = _floor_utc_bin(max(observed_times), bin_width_minutes)
        counts = {}
        for interval in location_intervals:
            if not (
                interval.available_to_charging_transition
                or interval.charging_to_available_transition
            ):
                continue
            bin_start = _floor_utc_bin(
                interval.interval_start_upper_utc, bin_width_minutes
            )
            starts, releases = counts.get(bin_start, (0, 0))
            counts[bin_start] = (
                starts + int(interval.available_to_charging_transition),
                releases + int(interval.charging_to_available_transition),
            )
        bin_start = first_bin
        while bin_start <= last_bin:
            starts, releases = counts.get(bin_start, (0, 0))
            bin_end = bin_start + timedelta(minutes=bin_width_minutes)
            result.append(TransitionFlowBin(
                ocpi_location_key=location_key,
                bin_start_utc=bin_start,
                bin_end_utc=bin_end,
                bin_width_minutes=bin_width_minutes,
                charging_start_proxy_count=starts,
                release_proxy_count=releases,
            ))
            bin_start = bin_end
    return result


def _floor_utc_bin(value: datetime, bin_width_minutes: int):
    value = _parse_timestamp(value).astimezone(timezone.utc)
    minute = (value.minute // bin_width_minutes) * bin_width_minutes
    return value.replace(minute=minute, second=0, microsecond=0)
