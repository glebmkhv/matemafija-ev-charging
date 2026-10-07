"""Readiness gates for a data-grounded baseline transition model."""
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

try:
    from .derivative_statistics import estimate_site_derivative_statistics
    from .flow import SiteCapacitySnapshot
    from .historical import EvseStateInterval
except ImportError:  # pragma: no cover
    from derivative_statistics import estimate_site_derivative_statistics
    from flow import SiteCapacitySnapshot
    from historical import EvseStateInterval


READINESS_VERSION = "1.0.0"


@dataclass(frozen=True)
class SiteReadinessMetadata:
    ocpi_location_key: str
    current_evse_count: int
    current_connector_count: int
    connectors_with_current_tariff_count: int
    tariff_component_types: tuple[str, ...] = ()
    matched_datex_station_count: int = 0

    def validate(self):
        counts = (self.current_evse_count, self.current_connector_count,
                  self.connectors_with_current_tariff_count,
                  self.matched_datex_station_count)
        if any(value < 0 for value in counts):
            raise ValueError("Readiness metadata counts cannot be negative")
        if self.connectors_with_current_tariff_count > self.current_connector_count:
            raise ValueError("Tariff-assigned connectors cannot exceed connectors")


@dataclass(frozen=True)
class SiteBaselineReadiness:
    ocpi_location_key: str
    history_span_days: float
    local_day_count: int
    total_snapshot_count: int
    eligible_snapshot_count: int
    eligible_expected_coverage: float
    evse_count: int
    observed_status_count: int
    complete_interval_count: int
    gap_affected_interval_count: int
    charging_start_proxy_count: int
    release_proxy_count: int
    complete_zero_availability_episode_count: int
    connector_count: int
    tariff_assigned_connector_count: int
    tariff_assignment_coverage: float | None
    tariff_component_types: tuple[str, ...]
    matched_datex_station_count: int
    descriptive_replay_ready: bool
    historical_profile_ready: bool
    transition_model_ready: bool
    f1_tariff_ready: bool
    assumption_driven_simulation_ready: bool
    readiness_tier: str
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    readiness_version: str = READINESS_VERSION

    def as_record(self):
        result = asdict(self)
        result["tariff_component_types"] = list(self.tariff_component_types)
        result["blocking_reasons"] = list(self.blocking_reasons)
        result["warnings"] = list(self.warnings)
        return result


@dataclass(frozen=True)
class BaselineReadinessSummary:
    site_count: int
    descriptive_replay_ready_count: int
    historical_profile_ready_count: int
    transition_model_ready_count: int
    f1_tariff_ready_count: int
    assumption_driven_simulation_ready_count: int
    datex_corroborated_count: int
    readiness_version: str = READINESS_VERSION

    def as_record(self):
        return asdict(self)


def assess_baseline_readiness(
    snapshots: Iterable[SiteCapacitySnapshot],
    intervals: Iterable[EvseStateInterval],
    evse_to_location: Mapping[str, str],
    metadata_by_location: Mapping[str, SiteReadinessMetadata] | None = None,
    *,
    local_timezone: str = "Europe/Vilnius",
    minimum_history_days: int = 7,
    minimum_local_days: int = 7,
    minimum_expected_coverage: float = 0.8,
    expected_cadence_seconds: int = 5 * 60,
    minimum_transition_count_each_direction: int = 20,
    minimum_complete_interval_count: int = 40,
    minimum_tariff_assignment_coverage: float = 1.0,
):
    """Assess readiness without fitting or simulating a transition model."""
    if minimum_transition_count_each_direction < 1:
        raise ValueError("minimum transition count must be positive")
    if minimum_complete_interval_count < 1:
        raise ValueError("minimum complete interval count must be positive")
    if not 0 < minimum_tariff_assignment_coverage <= 1:
        raise ValueError("minimum tariff coverage must be in (0, 1]")

    snapshot_rows = list(snapshots)
    interval_rows = list(intervals)
    metadata = dict(metadata_by_location or {})
    statistics = estimate_site_derivative_statistics(
        snapshot_rows,
        local_timezone=local_timezone,
        minimum_history_days=minimum_history_days,
        minimum_local_days=minimum_local_days,
        minimum_expected_coverage=minimum_expected_coverage,
        expected_cadence_seconds=expected_cadence_seconds,
        bootstrap_repetitions=100,
    )
    snapshots_by_location = {}
    for row in snapshot_rows:
        snapshots_by_location.setdefault(row.ocpi_location_key, []).append(row)
    intervals_by_location = {}
    for interval in interval_rows:
        location = evse_to_location.get(interval.ocpi_evse_key)
        if location is None:
            raise ValueError(f"Missing location for EVSE {interval.ocpi_evse_key}")
        intervals_by_location.setdefault(location, []).append(interval)

    results = []
    for statistic in statistics:
        location = statistic.ocpi_location_key
        site_snapshots = snapshots_by_location[location]
        site_intervals = intervals_by_location.get(location, [])
        site_metadata = metadata.get(location, SiteReadinessMetadata(
            ocpi_location_key=location,
            current_evse_count=len({row.ocpi_evse_key for row in site_intervals}),
            current_connector_count=0,
            connectors_with_current_tariff_count=0,
        ))
        site_metadata.validate()
        if site_metadata.ocpi_location_key != location:
            raise ValueError("Readiness metadata belongs to another location")

        statuses = {item.status for item in site_intervals}
        complete_intervals = [item for item in site_intervals
                              if not item.left_censored and not item.right_censored
                              and not item.contains_collection_gap]
        gap_count = sum(item.contains_collection_gap for item in site_intervals)
        start_count = sum(
            item.status == "available" and item.transition_to == "charging"
            for item in complete_intervals
        )
        release_count = sum(
            item.status == "charging" and item.transition_to == "available"
            for item in complete_intervals
        )
        descriptive_ready = (
            statistic.eligible_snapshot_count >= 2
            and any(item.offered_evse_count > 0 for item in site_snapshots)
        )
        historical_ready = statistic.statistically_qualified
        transition_ready = (
            historical_ready
            and len(statuses) >= 2
            and len(complete_intervals) >= minimum_complete_interval_count
            and start_count >= minimum_transition_count_each_direction
            and release_count >= minimum_transition_count_each_direction
        )
        tariff_coverage = (
            site_metadata.connectors_with_current_tariff_count
            / site_metadata.current_connector_count
            if site_metadata.current_connector_count else None
        )
        f1_ready = (
            tariff_coverage is not None
            and tariff_coverage >= minimum_tariff_assignment_coverage
            and bool(site_metadata.tariff_component_types)
        )
        simulation_ready = transition_ready and f1_ready

        blockers = list(statistic.qualification_reasons)
        if not descriptive_ready:
            blockers.append("insufficient_eligible_snapshots_for_descriptive_replay")
        if len(statuses) < 2:
            blockers.append("fewer_than_two_observed_statuses")
        if len(complete_intervals) < minimum_complete_interval_count:
            blockers.append(f"complete_interval_count_below_{minimum_complete_interval_count}")
        if start_count < minimum_transition_count_each_direction:
            blockers.append(f"charging_start_proxy_count_below_{minimum_transition_count_each_direction}")
        if release_count < minimum_transition_count_each_direction:
            blockers.append(f"release_proxy_count_below_{minimum_transition_count_each_direction}")
        if site_metadata.current_connector_count == 0:
            blockers.append("no_current_connectors")
        elif tariff_coverage < minimum_tariff_assignment_coverage:
            blockers.append(
                f"tariff_assignment_coverage_below_{minimum_tariff_assignment_coverage:.2f}"
            )
        if not site_metadata.tariff_component_types:
            blockers.append("no_observed_tariff_components")
        warnings = []
        if site_metadata.matched_datex_station_count == 0:
            warnings.append("no_matched_datex_station_for_corroboration")
        if gap_count:
            warnings.append("collection_gaps_present")
        if not statistic.episode_duration_statistically_qualified:
            warnings.append("scarcity_episode_duration_not_statistically_qualified")

        if simulation_ready:
            tier = "assumption_driven_simulation_ready"
        elif transition_ready:
            tier = "transition_ready_tariff_incomplete"
        elif historical_ready:
            tier = "historical_profile_only"
        elif descriptive_ready:
            tier = "descriptive_only"
        else:
            tier = "not_ready"
        results.append(SiteBaselineReadiness(
            ocpi_location_key=location,
            history_span_days=statistic.history_span_days,
            local_day_count=statistic.local_day_count,
            total_snapshot_count=statistic.total_snapshot_count,
            eligible_snapshot_count=statistic.eligible_snapshot_count,
            eligible_expected_coverage=statistic.eligible_expected_coverage,
            evse_count=site_metadata.current_evse_count,
            observed_status_count=len(statuses),
            complete_interval_count=len(complete_intervals),
            gap_affected_interval_count=gap_count,
            charging_start_proxy_count=start_count,
            release_proxy_count=release_count,
            complete_zero_availability_episode_count=(
                statistic.complete_zero_availability_episode_count
            ),
            connector_count=site_metadata.current_connector_count,
            tariff_assigned_connector_count=(
                site_metadata.connectors_with_current_tariff_count
            ),
            tariff_assignment_coverage=tariff_coverage,
            tariff_component_types=tuple(sorted(site_metadata.tariff_component_types)),
            matched_datex_station_count=site_metadata.matched_datex_station_count,
            descriptive_replay_ready=descriptive_ready,
            historical_profile_ready=historical_ready,
            transition_model_ready=transition_ready,
            f1_tariff_ready=f1_ready,
            assumption_driven_simulation_ready=simulation_ready,
            readiness_tier=tier,
            blocking_reasons=tuple(dict.fromkeys(blockers)),
            warnings=tuple(warnings),
        ))
    return results


def summarize_baseline_readiness(rows: Iterable[SiteBaselineReadiness]):
    items = list(rows)
    return BaselineReadinessSummary(
        site_count=len(items),
        descriptive_replay_ready_count=sum(x.descriptive_replay_ready for x in items),
        historical_profile_ready_count=sum(x.historical_profile_ready for x in items),
        transition_model_ready_count=sum(x.transition_model_ready for x in items),
        f1_tariff_ready_count=sum(x.f1_tariff_ready for x in items),
        assumption_driven_simulation_ready_count=sum(
            x.assumption_driven_simulation_ready for x in items
        ),
        datex_corroborated_count=sum(x.matched_datex_station_count > 0 for x in items),
    )


def load_site_readiness_metadata(connection):
    """Load structural, current-tariff and DATEX mapping facts from SQLite."""
    rows = connection.execute("""
        SELECT l.ocpi_location_key,
               COUNT(DISTINCT CASE WHEN e.is_current=1 THEN e.ocpi_evse_key END),
               COUNT(DISTINCT CASE WHEN c.is_current=1 THEN c.ocpi_connector_key END),
               COUNT(DISTINCT CASE WHEN c.is_current=1 AND a.is_current=1
                                   THEN c.ocpi_connector_key END),
               GROUP_CONCAT(DISTINCT pc.component_type),
               COUNT(DISTINCT CASE WHEN dl.is_current=1 THEN dl.source_entity_key END)
        FROM ocpi_locations l
        LEFT JOIN ocpi_evses e ON e.ocpi_location_key=l.ocpi_location_key
        LEFT JOIN ocpi_connectors c ON c.ocpi_evse_key=e.ocpi_evse_key
        LEFT JOIN ocpi_connector_tariff_assignments a
          ON a.ocpi_connector_key=c.ocpi_connector_key AND a.is_current=1
        LEFT JOIN ocpi_tariffs t ON t.ocpi_tariff_key=a.ocpi_tariff_key
        LEFT JOIN ocpi_tariff_price_components pc
          ON pc.source_entity_revision_id=t.current_revision_id
        LEFT JOIN charging_site_source_links ol
          ON ol.source_system='OCPI' AND ol.source_entity_type='OCPI_LOCATION'
         AND ol.source_entity_key=l.ocpi_location_key AND ol.is_current=1
        LEFT JOIN charging_site_source_links dl
          ON dl.charging_site_id=ol.charging_site_id
         AND dl.source_system='DATEX_II' AND dl.source_entity_type='DATEX_STATION'
         AND dl.is_current=1
        GROUP BY l.ocpi_location_key
    """).fetchall()
    return {row[0]: SiteReadinessMetadata(
        ocpi_location_key=row[0], current_evse_count=row[1],
        current_connector_count=row[2], connectors_with_current_tariff_count=row[3],
        tariff_component_types=tuple(sorted(filter(None, (row[4] or "").split(",")))),
        matched_datex_station_count=row[5],
    ) for row in rows}
