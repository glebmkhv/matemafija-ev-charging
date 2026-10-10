# Receiver-site eligibility contract

Status: **approved design contract v0.1; implementation pending**.

This document completes step 5 of the credit-circulation implementation plan.
It defines which alternative charging sites may enter a credit-backed choice
set. It does not determine the amount of a credit or the probability that an
alternative is selected; those belong to steps 6 and 10.

## 1. Meaning of receiver eligibility

A receiver is eligible only for **station-level scenario stress testing**. The
status means that the available evidence and projected pre-allocation state are
sufficient to include the site in a simulated choice set under the declared
policy gates.

It does not mean that:

- a real driver can or will travel there;
- the site supports a particular vehicle or connector;
- the operator accepts MATEMAFIJA credits;
- a parking or access restriction has been checked for an individual;
- capacity will still exist after travel time;
- the site is a production route recommendation.

## 2. Three-state decision

Every evaluated origin-receiver pair returns exactly one status:

| Status | Meaning | May enter choice set? |
| --- | --- | ---: |
| `eligible` | All mandatory scenario gates pass. Remaining limitations are disclosed as warnings. | yes |
| `ineligible` | Reliable evidence shows that at least one policy or physical gate fails. | no |
| `withheld` | Required evidence is missing, stale, inconsistent or otherwise insufficient for a valid decision. | no |

`withheld` is not equivalent to `ineligible`, and neither is equivalent to a
zero credit. Only `eligible` pairs may receive a numeric offer.

## 3. Evaluation state

Eligibility uses the receiver's **adaptive pre-redistribution state** at the
same UTC decision timestamp as the origin choice opportunity. This state
includes the paired simulation's local release/start projection but excludes
all cross-site allocations at that timestamp.

Using the pre-redistribution state prevents a circular rule in which a receiver
is declared eligible because the allocation being considered has already
changed its state.

The result records:

- origin and receiver site IDs;
- evaluation timestamp;
- source trajectory and replication IDs;
- observed/reconstructed source-state identity;
- projected pre-allocation state identity;
- eligibility-policy version;
- all gate inputs, results, reason codes and warnings.

## 4. MVP policy parameters

| Parameter | Initial value | Interpretation |
| --- | ---: | --- |
| `minimum_observation_coverage` | `0.80` | Same evidence-quality floor used by current scarcity/OSA contracts. |
| `maximum_equipment_unavailability_ratio` | `0.50` | Excludes equipment-dominated alternatives. |
| `maximum_receiver_scarcity_ratio` | `0.50` | Receiver must have at least half of effective operational capacity available before allocation. |
| `minimum_projected_available_evse_count` | `1` | At least one EVSE must be projected available. |
| `maximum_straight_line_distance_meters` | `5,000` | Initial Vilnius MVP candidate radius. |
| `maximum_state_age_seconds` | `600` | Receiver evidence cannot be older than twice the expected five-minute cadence. |
| `required_tariff_currency` | `EUR` | Needed for comparable contribution/credit presentation. |

These are versioned policy parameters, not empirical optima. Distance and
scarcity limits must later be varied in sensitivity analysis.

## 5. Identity and temporal gates

An origin-receiver pair is `ineligible` when:

- origin and receiver IDs are equal;
- receiver is outside the declared project geography;
- receiver is not current in the selected structural snapshot.

The decision is `withheld` when:

- either site identity is absent;
- the structure version is absent or inconsistent;
- the receiver has no state at the origin evaluation time;
- state age exceeds `maximum_state_age_seconds`;
- the receiver state belongs to another trajectory or replication;
- a collection gap makes the pre-allocation state indeterminate.

No future snapshot may be used to determine current eligibility.

## 6. Evidence-quality gates

The decision is `withheld` when:

- `valid_observation_coverage` is missing or below `0.80`;
- offered, operational, available, non-operational or indeterminate counts are
  missing or internally inconsistent;
- availability or equipment ratios cannot be computed;
- the underlying source snapshot was incomplete or unsuccessful;
- a projected state has no traceable reconstructed source state.

Unknown data are never converted to zero equipment loss or zero scarcity.

## 7. Capacity and scarcity gates

The receiver is `ineligible` when any of the following reliably holds:

- `offered_evse_count <= 0`;
- `effective_operational_capacity <= 0`;
- projected pre-allocation available EVSE count is below `1`;
- projected zero availability is true;
- projected receiver scarcity exceeds `0.50`;
- equipment-unavailability ratio exceeds `0.50`.

Projected receiver scarcity is:

\[
C_j^{pre}(t)=1-
\frac{A_j^{pre}(t)}{K_j^{effective}(t)}.
\]

Eligibility does not consume capacity. The downstream reservation layer applies
its own usable-capacity fraction and globally serializes competing origins.

## 8. Spatial gate

Coordinates must be observed OCPI coordinates or explicitly reconstructed from
a reviewed mapping. The decision is `withheld` if coordinates are absent,
invalid or derived from an unreviewed ambiguous mapping.

For MVP candidate generation, distance is the haversine straight-line distance:

\[
d_{ij}^{geo} \leq 5{,}000\ \text{meters}.
\]

A pair outside the radius is `ineligible`. Distance inside the radius does not
prove a practical route; road travel time and distance remain unavailable
unless a separately versioned routing source is introduced.

## 9. Tariff gate

The receiver requires a complete current F1 tariff assignment under the
existing `f1_tariff_ready` definition and a resolvable EUR component structure.

- reliable non-EUR tariff: `ineligible` for the initial EUR-only policy;
- incomplete assignment, missing price component or ambiguous applicability:
  `withheld`;
- complete EUR structure: gate passes.

F1 readiness permits comparison and display. It does not provide a complete
session bill without applicable Session/CDR quantities.

## 10. Access and opening gate

When source data reliably state that a receiver is closed and charging is not
allowed while closed, it is `ineligible` at that local time.

When opening/access information required for a decision is absent or
contradictory, the result is `withheld`. If OCPI explicitly permits charging
while closed, the opening-time gate passes with that evidence recorded.

Parking rules, private-site permissions and physical accessibility that are not
represented in current normalized data remain warnings and pilot-data
requirements; they must not be silently described as verified.

## 11. Compatibility boundary

The public infrastructure data may describe connector standards and power, but
the current model has no observed vehicle capability. Therefore the MVP cannot
prove individual vehicle-site compatibility.

For station-level stress testing:

- absence of vehicle capability does not automatically remove an otherwise
  eligible receiver;
- the result must carry warning `vehicle_compatibility_unresolved`;
- the interface must not label the output a personalized recommendation.

A future user-facing pilot must add a hard compatibility gate using declared or
contractually available vehicle requirements. Unknown compatibility in that
mode becomes `withheld`.

Cross-operator credit acceptance is likewise unresolved. It is a governance
warning in the simulator and a hard contractual requirement for real issuance.

## 12. Deterministic decision precedence

When several conditions apply, the evaluator uses this order:

1. invalid/missing identity or inconsistent trajectory -> `withheld`;
2. same origin and receiver or out-of-scope structure -> `ineligible`;
3. missing/stale/inconsistent state -> `withheld`;
4. failed evidence coverage -> `withheld`;
5. no operational capacity or excessive equipment loss -> `ineligible`;
6. no projected availability or excess receiver scarcity -> `ineligible`;
7. missing/unreviewed coordinates -> `withheld`;
8. distance outside radius -> `ineligible`;
9. unresolved tariff -> `withheld`; reliable non-EUR tariff -> `ineligible`;
10. closed access -> `ineligible`; unresolved required access -> `withheld`;
11. otherwise -> `eligible`, with all unresolved non-personalized warnings.

The result retains every evaluated gate, not only the first terminal reason.
The precedence defines the primary reason code and makes reporting stable.

## 13. Reason codes

Canonical primary reason codes include:

```text
eligible
missing_identity
structure_version_mismatch
same_as_origin
outside_project_scope
receiver_not_current
receiver_state_missing
receiver_state_stale
trajectory_or_replication_mismatch
collection_gap_or_incomplete_snapshot
coverage_below_threshold
state_counts_inconsistent
no_effective_operational_capacity
equipment_unavailability_above_guard
projected_availability_below_minimum
receiver_scarcity_above_limit
coordinates_missing_or_unreviewed
distance_above_limit
f1_tariff_incomplete
tariff_currency_not_supported
receiver_closed
access_information_unresolved
```

Warnings include:

```text
vehicle_compatibility_unresolved
road_travel_cost_unresolved
parking_conditions_unresolved
physical_accessibility_unresolved
cross_operator_acceptance_unresolved
future_capacity_not_guaranteed
```

Reason codes are machine-readable and versioned. Human-facing labels must not
change their factual meaning.

## 14. Choice-set construction

For one origin opportunity:

1. evaluate every structurally current candidate independently;
2. retain only `eligible` pairs;
3. sort by distance, then receiver site ID;
4. freeze the site IDs, state identities, distances, gate results and warnings
   in `choice_set_created`;
5. pass the immutable set to the step-6 allocation rule;
6. do not reclassify a receiver inside the choice response draw.

If no receiver is eligible, emit an empty choice set plus the complete status
counts and primary reasons. Do not create a numeric offer and do not describe
the result as available redistribution.

## 15. Required outputs

The receiver-eligibility report contains:

- evaluated, eligible, ineligible and withheld pair counts;
- primary-reason distribution;
- warning distribution;
- distance distribution for eligible pairs;
- projected capacity and scarcity inputs;
- tariff and access gate status;
- source-state and structure versions;
- eligibility-policy parameters and version.

## 16. Step-five acceptance decision

The initial receiver contract admits only current, temporally aligned,
quality-qualified, operationally healthy, sufficiently available, nearby and
EUR-tariff-resolvable sites. It preserves unresolved vehicle, route, parking,
accessibility and cross-operator limitations as explicit warnings and does not
claim personalized suitability. Step 6 may now determine how available pool MCU
is divided into offers across the eligible immutable choice set.
