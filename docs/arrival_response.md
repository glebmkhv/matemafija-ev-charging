# Charging-start (arrival-response proxy) channel

Status: **implemented v1.0.0 compatibility profile and typed v2.0.0 profile**.

`src/arrival_response.py` modifies only the observed accepted-use proxy:

```text
available -> charging  (`charging_start_proxy`)
```

It is not a count of all vehicle arrivals, rejected drivers or a physical
queue.

## Mathematical form

```text
h_start,1(i,t) = h_start,0(i,t)
                 * exp(-theta_arrival * d_i(t - tau))
```

`h_start,0` is the qualified historical charging-start hazard, `d_i` is the
policy-defined effective adjustment in `EUR/min`, `theta_arrival >= 0` is an
assumed sensitivity in `min/EUR`, and `tau` is the assumed delay. Probability
over decision interval `Delta` is `1 - exp(-h_start,1 * Delta)`. Zero driver or
zero sensitivity reproduces baseline exactly.

## Simulator integration

The paired runner draws starts from source available EVSEs and releases from
source charging EVSEs with common random numbers:

```text
A' = A + releases - starts
C' = C - releases + starts
```

Operational capacity is conserved. `theta_arrival` is an additional scenario
axis and defaults to zero, preserving release-only experiments.

## Displaced-demand guardrail

`fixed_start_proxy_count - adaptive_start_proxy_count` is reported as
`deferred_or_displaced_start_proxy_count`. It is not called lost demand: data
cannot distinguish delay, use of another station, use outside the window or
abandonment. Every scarcity/robustness result exposes this trade-off. Improving
availability by suppressing accepted starts is not automatically a welfare
improvement.

The optional downstream allocation is implemented in
[`spatial_redistribution.md`](spatial_redistribution.md). Any part not allocated
under its explicit distance/capacity assumptions remains unassigned.

## Claim boundary

Sensitivity is assumed, adjusted transitions are simulated, and conclusions
remain scenario-conditional. This channel does not estimate price elasticity,
total arrivals, queues, waiting time, served trips or causal demand destruction.

## Typed v2 accepted-start profile

The executable v2 form retains the same mechanism with an explicitly typed
origin signal:

```text
h_start,2 = h_start,0 * exp(
    -theta_start_price * delayed_origin_price_contribution_rate
)
```

The signal is `EUR/min` with `policy_defined` provenance; sensitivity is
`min/EUR` and delay is an independent assumed non-negative integer number of
minutes. The v2 evaluator rejects withheld, non-applicable, negative,
unit-mismatched, future and duplicate signals. Its result reconciles the
exponent, multiplier and adjusted hazard.

Alternative-site credits deliberately do not enter this origin equation. They
operate later in destination choice. This prevents one credit from being
counted both as the reason an origin start disappeared and as the reason a
receiver was selected.

## Unit-level redistribution candidates

Simulation grid v2.1 retains the common random number for every source
available-EVSE draw. A `RedistributionCandidate` is created exactly when:

```text
adaptive_start_probability <= paired_uniform < baseline_start_probability
```

Thus the fixed arm contains a start proxy and the adaptive arm does not. Every
candidate records:

- stable candidate, scenario and replication identities;
- origin site/entity and UTC timestamp;
- source available-unit index and paired uniform;
- baseline and adaptive start probabilities;
- explicit scenario-conditional claim scope and simulated provenance.

The candidate is not a person, vehicle, rejected arrival or proven trip. It is
one traceable counterfactual opportunity eligible for the later choice layer.

For every run and timestamp the simulator enforces:

```text
candidate_count
  = fixed_start_proxy_count - adaptive_start_proxy_count
  = deferred_or_displaced_start_proxy_count
```

Candidate IDs must be unique. The spatial compatibility adapter now aggregates
these validated records instead of independently recalculating demand from
totals. The implemented credit-sensitive receiver-choice contract is documented
in [`receiver_choice.md`](receiver_choice.md).
