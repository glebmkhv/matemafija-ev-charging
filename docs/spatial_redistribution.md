# Capacity-constrained spatial redistribution

Status: **implemented assumption-driven layer v1.0.0**.

`src/spatial_redistribution.py` implements step 15. It allocates only the
already simulated `deferred_or_displaced_start_proxy_count` between OCPI
locations with coordinates and available receiving capacity.

## 1. Inputs and provenance

- origin proxy counts: `simulated`;
- destination adaptive projected availability: `simulated`;
- OCPI coordinates: `observed` (or explicitly reconstructed);
- maximum distance, redistribution probability and usable receiver-capacity
  fraction: `assumed`;
- random seed: reproducibility control.

Locations without usable coordinates cannot participate silently. Current
coordinates are loaded directly from `ocpi_locations`; DATEX coordinates are
not substituted without an explicit reviewed mapping.

## 2. Candidate generation

For each displaced start proxy, a seeded Bernoulli draw with
`redistribution_probability` determines whether it becomes a redistribution
candidate. Non-candidates remain `unresolved_or_nonparticipating`; they are not
called abandoned demand.

Usable destination capacity is conservatively bounded by:

```text
floor(projected_available_evse_count * receiver_capacity_fraction)
```

The fraction can reserve capacity against over-aggressive redistribution.

## 3. Allocation rule

Candidate origin-destination edges must:

- share the same simulation timestamp;
- refer to different stations;
- lie within `maximum_distance_meters` by haversine distance;
- have remaining receiving capacity.

`global_nearest_first_v1` sorts all eligible edges globally by distance and
allocates integer proxy starts without exceeding either remaining origin flow
or destination capacity. Stable site IDs break equal-distance ties, making the
result reproducible.

## 4. Conservation and scarcity-transfer guardrails

For every origin:

```text
displaced = allocated + total_unassigned
candidate = allocated + network_unallocated_candidate
```

For every destination:

```text
available_after = available_before - allocated
allocated <= usable_receiving_capacity
```

The result reports `destination_zero_availability_created_count`. Thus an
origin's scarcity improvement cannot hide newly created zero availability at a
receiver.

## 5. Current limitations

- Distance is straight-line distance, not road travel time.
- No vehicle-specific connector, power, accessibility or operator preference
  is observed, so compatibility is not asserted.
- Allocation occurs inside one decision timestamp; travel-time lag and future
  carry-over are absent.
- A proxy allocated to another station is not proof that a real driver made
  that trip.
- Spatial results are not yet folded back into the per-site robustness score;
  they are a separate network trade-off output.

These limitations must remain visible in the interface and pitch. The output
is `simulated`, `scenario_conditional`, and suitable for stress testing—not a
mobility forecast or route recommendation.

