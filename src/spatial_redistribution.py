"""Capacity-constrained spatial allocation of displaced charging-start proxies."""

from dataclasses import dataclass
from datetime import datetime
import math
import random

try:
    from .simulation_contract import ClaimScope, ProvenanceClass
except ImportError:  # pragma: no cover
    from simulation_contract import ClaimScope, ProvenanceClass


SPATIAL_REDISTRIBUTION_VERSION = "1.0.0"
EARTH_RADIUS_METERS = 6_371_000.0


@dataclass(frozen=True)
class SpatialSite:
    site_id: str
    latitude: float
    longitude: float
    provenance: ProvenanceClass = ProvenanceClass.OBSERVED

    def validate(self):
        if not self.site_id:
            raise ValueError("Spatial site ID is required")
        if (not math.isfinite(self.latitude) or not -90 <= self.latitude <= 90
                or not math.isfinite(self.longitude)
                or not -180 <= self.longitude <= 180):
            raise ValueError("Spatial site coordinates are invalid")
        if self.provenance not in (
            ProvenanceClass.OBSERVED, ProvenanceClass.RECONSTRUCTED,
        ):
            raise ValueError("Spatial coordinates must be observed or reconstructed")


@dataclass(frozen=True)
class SpatialRedistributionSpecification:
    maximum_distance_meters: float
    redistribution_probability: float
    receiver_capacity_fraction: float = 1.0
    allocation_rule: str = "global_nearest_first_v1"
    provenance: ProvenanceClass = ProvenanceClass.ASSUMED

    def validate(self):
        values = (
            self.maximum_distance_meters,
            self.redistribution_probability,
            self.receiver_capacity_fraction,
        )
        if any(isinstance(value, bool) or not math.isfinite(value) for value in values):
            raise ValueError("Spatial redistribution parameters must be finite")
        if self.maximum_distance_meters <= 0:
            raise ValueError("Maximum redistribution distance must be positive")
        if not 0 <= self.redistribution_probability <= 1:
            raise ValueError("Redistribution probability must be in [0, 1]")
        if not 0 <= self.receiver_capacity_fraction <= 1:
            raise ValueError("Receiver capacity fraction must be in [0, 1]")
        if self.allocation_rule != "global_nearest_first_v1":
            raise ValueError("Unsupported spatial allocation rule")
        if self.provenance is not ProvenanceClass.ASSUMED:
            raise ValueError("Spatial redistribution parameters must be assumed")


@dataclass(frozen=True)
class DisplacedStartProxy:
    origin_site_id: str
    evaluation_time_utc: datetime
    displaced_start_proxy_count: int
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED

    def validate(self):
        if not self.origin_site_id or self.evaluation_time_utc.tzinfo is None:
            raise ValueError("Displaced proxy requires site and aware timestamp")
        if (isinstance(self.displaced_start_proxy_count, bool)
                or not isinstance(self.displaced_start_proxy_count, int)
                or self.displaced_start_proxy_count < 0):
            raise ValueError("Displaced start proxy count must be non-negative integer")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Displaced start proxy must be simulated")


@dataclass(frozen=True)
class ReceivingCapacity:
    destination_site_id: str
    evaluation_time_utc: datetime
    projected_available_evse_count: int
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED

    def validate(self):
        if not self.destination_site_id or self.evaluation_time_utc.tzinfo is None:
            raise ValueError("Receiving capacity requires site and aware timestamp")
        if (isinstance(self.projected_available_evse_count, bool)
                or not isinstance(self.projected_available_evse_count, int)
                or self.projected_available_evse_count < 0):
            raise ValueError("Receiving capacity must be non-negative integer")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Receiving capacity must be simulated")


@dataclass(frozen=True)
class SpatialAllocation:
    evaluation_time_utc: datetime
    origin_site_id: str
    destination_site_id: str
    distance_meters: float
    allocated_start_proxy_count: int
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED

    def validate(self, specification):
        if (self.evaluation_time_utc.tzinfo is None
                or not self.origin_site_id or not self.destination_site_id
                or self.origin_site_id == self.destination_site_id):
            raise ValueError("Spatial allocation identity is invalid")
        if (not math.isfinite(self.distance_meters)
                or not 0 <= self.distance_meters <= specification.maximum_distance_meters
                or self.allocated_start_proxy_count <= 0):
            raise ValueError("Spatial allocation distance or count is invalid")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Spatial allocation must be simulated")


@dataclass(frozen=True)
class OriginRedistributionOutcome:
    evaluation_time_utc: datetime
    origin_site_id: str
    displaced_start_proxy_count: int
    redistribution_candidate_count: int
    allocated_start_proxy_count: int
    network_unallocated_candidate_count: int
    unresolved_or_nonparticipating_count: int
    total_unassigned_count: int

    def validate(self):
        if self.evaluation_time_utc.tzinfo is None or not self.origin_site_id:
            raise ValueError("Origin outcome identity is invalid")
        values = (
            self.displaced_start_proxy_count,
            self.redistribution_candidate_count,
            self.allocated_start_proxy_count,
            self.network_unallocated_candidate_count,
            self.unresolved_or_nonparticipating_count,
            self.total_unassigned_count,
        )
        if any(value < 0 for value in values):
            raise ValueError("Origin outcome counts cannot be negative")
        if (self.redistribution_candidate_count > self.displaced_start_proxy_count
                or self.allocated_start_proxy_count > self.redistribution_candidate_count
                or self.network_unallocated_candidate_count
                != self.redistribution_candidate_count-self.allocated_start_proxy_count
                or self.total_unassigned_count
                != self.displaced_start_proxy_count-self.allocated_start_proxy_count):
            raise ValueError("Origin redistribution accounting is inconsistent")


@dataclass(frozen=True)
class DestinationRedistributionOutcome:
    evaluation_time_utc: datetime
    destination_site_id: str
    source_available_evse_count: int
    usable_receiving_capacity: int
    allocated_start_proxy_count: int
    projected_available_after_redistribution: int
    zero_availability_before_redistribution: bool
    zero_availability_after_redistribution: bool

    def validate(self):
        if self.evaluation_time_utc.tzinfo is None or not self.destination_site_id:
            raise ValueError("Destination outcome identity is invalid")
        if min(
            self.source_available_evse_count,
            self.usable_receiving_capacity,
            self.allocated_start_proxy_count,
            self.projected_available_after_redistribution,
        ) < 0:
            raise ValueError("Destination counts cannot be negative")
        if (self.zero_availability_before_redistribution
                != (self.source_available_evse_count == 0)
                or self.zero_availability_after_redistribution
                != (self.projected_available_after_redistribution == 0)):
            raise ValueError("Destination zero-availability flags are inconsistent")


@dataclass(frozen=True)
class SpatialRedistributionResult:
    specification: SpatialRedistributionSpecification
    random_seed: int
    allocations: tuple[SpatialAllocation, ...]
    origin_outcomes: tuple[OriginRedistributionOutcome, ...]
    destination_outcomes: tuple[DestinationRedistributionOutcome, ...]
    total_displaced_start_proxy_count: int
    total_candidate_count: int
    total_allocated_start_proxy_count: int
    total_unassigned_count: int
    destination_zero_availability_created_count: int
    claim_scope: ClaimScope = ClaimScope.SCENARIO_CONDITIONAL
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED
    redistribution_version: str = SPATIAL_REDISTRIBUTION_VERSION

    def validate(self):
        self.specification.validate()
        if (isinstance(self.random_seed, bool)
                or not isinstance(self.random_seed, int)
                or self.random_seed < 0):
            raise ValueError("Redistribution seed must be non-negative")
        for allocation in self.allocations:
            allocation.validate(self.specification)
        for origin in self.origin_outcomes:
            origin.validate()
        for destination in self.destination_outcomes:
            destination.validate()
        origin_input = sum(item.displaced_start_proxy_count for item in self.origin_outcomes)
        candidates = sum(item.redistribution_candidate_count for item in self.origin_outcomes)
        allocated = sum(item.allocated_start_proxy_count for item in self.origin_outcomes)
        unassigned = sum(item.total_unassigned_count for item in self.origin_outcomes)
        if (origin_input != self.total_displaced_start_proxy_count
                or candidates != self.total_candidate_count
                or allocated != self.total_allocated_start_proxy_count
                or unassigned != self.total_unassigned_count
                or allocated + unassigned != origin_input):
            raise ValueError("Spatial redistribution accounting is inconsistent")
        if sum(item.allocated_start_proxy_count for item in self.allocations) != allocated:
            raise ValueError("Spatial allocation rows do not match origin totals")
        if sum(item.allocated_start_proxy_count for item in self.destination_outcomes) != allocated:
            raise ValueError("Destination allocations do not match origin totals")
        for destination in self.destination_outcomes:
            if (destination.allocated_start_proxy_count
                    > destination.usable_receiving_capacity
                    or destination.projected_available_after_redistribution
                    != destination.source_available_evse_count
                    - destination.allocated_start_proxy_count):
                raise ValueError("Receiving capacity was exceeded")
        created = sum(
            not item.zero_availability_before_redistribution
            and item.zero_availability_after_redistribution
            for item in self.destination_outcomes
        )
        if created != self.destination_zero_availability_created_count:
            raise ValueError("Destination scarcity transfer count is inconsistent")
        if self.claim_scope is not ClaimScope.SCENARIO_CONDITIONAL:
            raise ValueError("Spatial result must remain scenario-conditional")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Spatial result must have simulated provenance")


def redistribute_displaced_start_proxies(
    sites,
    displaced_proxies,
    receiving_capacities,
    specification: SpatialRedistributionSpecification,
    *,
    random_seed: int,
):
    """Allocate candidate proxy starts to nearest capacity without overbooking."""
    specification.validate()
    if isinstance(random_seed, bool) or not isinstance(random_seed, int) or random_seed < 0:
        raise ValueError("Redistribution seed must be non-negative integer")
    site_rows = tuple(sites)
    site_by_id = {item.site_id: item for item in site_rows}
    if len(site_by_id) != len(site_rows):
        raise ValueError("Spatial site IDs must be unique")
    for site in site_rows:
        site.validate()
    demands = tuple(displaced_proxies)
    capacities = tuple(receiving_capacities)
    for item in demands:
        item.validate()
    for item in capacities:
        item.validate()
    if any(item.origin_site_id not in site_by_id for item in demands):
        raise ValueError("Displaced origin lacks spatial metadata")
    if any(item.destination_site_id not in site_by_id for item in capacities):
        raise ValueError("Receiving destination lacks spatial metadata")
    demand_keys = [(item.evaluation_time_utc, item.origin_site_id) for item in demands]
    capacity_keys = [
        (item.evaluation_time_utc, item.destination_site_id) for item in capacities
    ]
    if len(demand_keys) != len(set(demand_keys)):
        raise ValueError("Duplicate displaced origin at one timestamp")
    if len(capacity_keys) != len(set(capacity_keys)):
        raise ValueError("Duplicate receiving capacity at one timestamp")

    rng = random.Random(random_seed)
    candidate_by_key = {}
    remaining_by_origin = {}
    for demand in sorted(demands, key=lambda item: (
        item.evaluation_time_utc, item.origin_site_id,
    )):
        candidate_count = sum(
            rng.random() < specification.redistribution_probability
            for _ in range(demand.displaced_start_proxy_count)
        )
        key = (demand.evaluation_time_utc, demand.origin_site_id)
        candidate_by_key[key] = candidate_count
        remaining_by_origin[key] = candidate_count

    source_capacity = {}
    remaining_capacity = {}
    for capacity in capacities:
        key = (capacity.evaluation_time_utc, capacity.destination_site_id)
        usable = math.floor(
            capacity.projected_available_evse_count
            * specification.receiver_capacity_fraction
        )
        source_capacity[key] = (capacity.projected_available_evse_count, usable)
        remaining_capacity[key] = usable

    edges = []
    for demand in demands:
        origin = site_by_id[demand.origin_site_id]
        for capacity in capacities:
            if (capacity.evaluation_time_utc != demand.evaluation_time_utc
                    or capacity.destination_site_id == demand.origin_site_id):
                continue
            destination = site_by_id[capacity.destination_site_id]
            distance = haversine_distance_meters(origin, destination)
            if distance <= specification.maximum_distance_meters:
                edges.append((
                    distance, demand.evaluation_time_utc,
                    demand.origin_site_id, capacity.destination_site_id,
                ))
    edges.sort(key=lambda item: (item[0], item[1], item[2], item[3]))

    allocations = []
    for distance, at, origin_id, destination_id in edges:
        origin_key = (at, origin_id)
        destination_key = (at, destination_id)
        count = min(
            remaining_by_origin[origin_key],
            remaining_capacity[destination_key],
        )
        if count <= 0:
            continue
        remaining_by_origin[origin_key] -= count
        remaining_capacity[destination_key] -= count
        allocations.append(SpatialAllocation(
            evaluation_time_utc=at,
            origin_site_id=origin_id,
            destination_site_id=destination_id,
            distance_meters=distance,
            allocated_start_proxy_count=count,
        ))

    allocated_by_origin = {}
    allocated_by_destination = {}
    for item in allocations:
        origin_key = (item.evaluation_time_utc, item.origin_site_id)
        destination_key = (item.evaluation_time_utc, item.destination_site_id)
        allocated_by_origin[origin_key] = (
            allocated_by_origin.get(origin_key, 0) + item.allocated_start_proxy_count
        )
        allocated_by_destination[destination_key] = (
            allocated_by_destination.get(destination_key, 0)
            + item.allocated_start_proxy_count
        )

    origin_outcomes = []
    for demand in demands:
        key = (demand.evaluation_time_utc, demand.origin_site_id)
        candidate = candidate_by_key[key]
        allocated = allocated_by_origin.get(key, 0)
        nonparticipating = demand.displaced_start_proxy_count - candidate
        network_unallocated = candidate - allocated
        origin_outcomes.append(OriginRedistributionOutcome(
            evaluation_time_utc=demand.evaluation_time_utc,
            origin_site_id=demand.origin_site_id,
            displaced_start_proxy_count=demand.displaced_start_proxy_count,
            redistribution_candidate_count=candidate,
            allocated_start_proxy_count=allocated,
            network_unallocated_candidate_count=network_unallocated,
            unresolved_or_nonparticipating_count=nonparticipating,
            total_unassigned_count=nonparticipating + network_unallocated,
        ))

    destination_outcomes = []
    for capacity in capacities:
        key = (capacity.evaluation_time_utc, capacity.destination_site_id)
        source_available, usable = source_capacity[key]
        allocated = allocated_by_destination.get(key, 0)
        destination_outcomes.append(DestinationRedistributionOutcome(
            evaluation_time_utc=capacity.evaluation_time_utc,
            destination_site_id=capacity.destination_site_id,
            source_available_evse_count=source_available,
            usable_receiving_capacity=usable,
            allocated_start_proxy_count=allocated,
            projected_available_after_redistribution=source_available-allocated,
            zero_availability_before_redistribution=source_available == 0,
            zero_availability_after_redistribution=(
                source_available-allocated == 0
            ),
        ))

    result = SpatialRedistributionResult(
        specification=specification,
        random_seed=random_seed,
        allocations=tuple(allocations),
        origin_outcomes=tuple(origin_outcomes),
        destination_outcomes=tuple(destination_outcomes),
        total_displaced_start_proxy_count=sum(
            item.displaced_start_proxy_count for item in demands
        ),
        total_candidate_count=sum(candidate_by_key.values()),
        total_allocated_start_proxy_count=sum(
            item.allocated_start_proxy_count for item in allocations
        ),
        total_unassigned_count=sum(
            item.total_unassigned_count for item in origin_outcomes
        ),
        destination_zero_availability_created_count=sum(
            item.source_available_evse_count > 0
            and item.projected_available_after_redistribution == 0
            for item in destination_outcomes
        ),
    )
    result.validate()
    return result


def displaced_proxies_from_run(origin_site_id, run):
    """Adapt one paired simulation run into timestamped displaced proxies."""
    run.validate()
    return tuple(DisplacedStartProxy(
        origin_site_id=origin_site_id,
        evaluation_time_utc=point.evaluation_time_utc,
        displaced_start_proxy_count=(
            point.fixed_start_count - point.adaptive_start_count
            if point.comparison_eligible else 0
        ),
    ) for point in run.points)


def receiving_capacities_from_run(destination_site_id, run):
    """Expose adaptive projected availability as bounded receiving capacity."""
    run.validate()
    return tuple(ReceivingCapacity(
        destination_site_id=destination_site_id,
        evaluation_time_utc=point.evaluation_time_utc,
        projected_available_evse_count=(
            point.adaptive_projected_available_count
            if point.comparison_eligible else 0
        ),
    ) for point in run.points)


def load_spatial_sites(connection):
    """Load current OCPI locations with usable coordinates from SQLite v2."""
    rows = connection.execute("""
        SELECT ocpi_location_key, latitude, longitude
        FROM ocpi_locations
        WHERE is_current=1 AND latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY ocpi_location_key
    """).fetchall()
    result = tuple(SpatialSite(row[0], row[1], row[2]) for row in rows)
    for item in result:
        item.validate()
    return result


def haversine_distance_meters(origin: SpatialSite, destination: SpatialSite):
    origin.validate()
    destination.validate()
    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(destination.latitude)
    delta_lat = lat2-lat1
    delta_lon = math.radians(destination.longitude-origin.longitude)
    value = (
        math.sin(delta_lat/2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon/2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * math.asin(min(1.0, math.sqrt(value)))
