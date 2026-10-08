# Charging-start (arrival-response proxy) channel

Status: **implemented assumption-driven mechanism v1.0.0**.

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

Step 15 may spatially allocate this proxy flow under explicit rules. Until then
it remains unassigned and cannot increase another station's load.

## Claim boundary

Sensitivity is assumed, adjusted transitions are simulated, and conclusions
remain scenario-conditional. This channel does not estimate price elasticity,
total arrivals, queues, waiting time, served trips or causal demand destruction.

