# Observable capacity-scarcity metrics

This document defines evidence that a charging location had no immediately
available operational EVSE. It deliberately does not claim that a physical
queue existed, that an arriving driver was rejected, or that a user waited.

The implementation is in `src/scarcity.py` and consumes the source-native OCPI
location snapshots produced by `src/flow.py`.

## 1. Eligibility

A snapshot is eligible for scarcity evidence only when:

1. `effective_operational_capacity > 0`;
2. `valid_observation_coverage >= minimum_coverage_required`;
3. `available_evse_count` is known.

The current engineering default for minimum coverage is `0.8`. It is not a
policy threshold and must be included in every result.

An ineligible snapshot is `unknown`, not evidence of either scarcity or normal
availability.

## 2. Snapshot metrics

For an eligible location snapshot at time `t`:

```text
availability_ratio(t)
    = available_evse_count(t) / effective_operational_capacity(t)

operational_scarcity_ratio(t)
    = 1 - availability_ratio(t)

zero_availability_evidence(t)
    = [available_evse_count(t) = 0]
```

`operational_scarcity_ratio` describes how little immediately available
operational capacity was reported. It does not measure a queue.

Equipment failure is measured separately:

```text
equipment_unavailability_ratio(t)
    = non_operational_evse_count(t) / offered_evse_count(t)
```

Unknown, blocked and unrecognized states are also separate:

```text
indeterminate_capacity_ratio(t)
    = indeterminate_evse_count(t) / offered_evse_count(t)
```

This separation prevents a fully broken station from being presented as a
demand-driven scarcity event.

## 3. Zero-availability episodes

A zero-availability episode is a contiguous run of eligible snapshots for the
same OCPI location where `zero_availability_evidence = true`.

The run is split when:

- a valid non-zero-availability snapshot is observed;
- an ineligible snapshot occurs;
- the interval between snapshots exceeds `2 × expected cadence`.

The physical start and end are interval-censored:

```text
start_lower = last contiguous eligible false snapshot
start_upper = first true snapshot
end_lower   = last true snapshot
end_upper   = first contiguous eligible false snapshot
```

For a fully bounded episode:

```text
duration_lower = end_lower - start_upper
duration_upper = end_upper - start_lower
duration_midpoint = (duration_lower + duration_upper) / 2
```

If either false boundary is absent, the episode is left- or right-censored and
its upper duration is not reported. An ineligible snapshot does not prove that
availability recovered.

## 4. Descriptive site summary

For each location and analysis window the implementation reports:

- total, eligible and ineligible snapshot counts;
- zero-availability snapshot count;
- `zero_availability_snapshot_share`;
- episode count and complete episode count;
- sum of conservative lower episode durations;
- mean availability ratio;
- mean operational scarcity ratio;
- mean equipment-unavailability ratio.

`zero_availability_snapshot_share` is:

```text
eligible zero-availability snapshots / all eligible snapshots
```

It is a cadence-dependent descriptive share, not yet an estimated probability
and not a probability of queueing. Statistical uncertainty and time weighting
belong to the next derivative-statistics stage.

## 5. What these metrics prove

They can support the statement:

> During the measured period, this location repeatedly reported no immediately
> available EVSE despite having positive operational capacity.

They cannot alone support:

- a driver was waiting;
- a driver abandoned the location;
- post-charge idle caused the event;
- an idle fee would have released capacity;
- a particular user harmed another user.

Those claims require additional observations, a validated estimator, or a
causal intervention.

## 6. Current scope

- Aggregation level: source-native OCPI location.
- Time basis: UTC observation time.
- Inputs: successful complete OCPI location snapshots.
- DATEX: not combined at this stage.
- Queue variables: absent.
- Policy thresholds and adaptive fee: absent.
