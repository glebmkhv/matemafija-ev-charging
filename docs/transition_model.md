# Baseline state-transition model

The baseline model estimates observable EVSE state-transition hazards for the
common simulator. Its implementation is `src/transition_model.py`, version
`1.0.0`.

It is a descriptive model of the observed system before an adaptive-policy
response is applied. It does not estimate a causal price effect.

## Channels

The MVP contains exactly two price-relevant observable channels:

| Channel | Observed transition | Correct interpretation |
| --- | --- | --- |
| `charging_start_proxy` | `available -> charging` | Start-of-use proxy among accepted uses. It is not total arrivals or demand. |
| `release_proxy` | `charging -> available` | Return-to-availability proxy. It is not exact charge completion or post-charge idle. |

Transitions involving `outoforder`, `inoperative`, `unknown`, `blocked` or
`reserved` are not modified by these price-response channels. Other exits from
a source state remain competing events in the hazard denominator.

## Eligible evidence

A site is fitted only when `transition_model_ready=true` under
`docs/baseline_readiness.md`. An absent or failed readiness assessment causes a
hard error.

The estimator uses only state intervals that are:

- bounded at both ends;
- neither left- nor right-censored;
- unaffected by a collection gap;
- positive in duration after reconstruction.

Because exact transition times are interval-censored, the initial estimator
uses the midpoint of each reconstructed start and end bound. The model records
the training window and included/excluded interval counts so this approximation
is auditable.

## Estimator

For channel `c`, site `i` and time stratum `g`, the cause-specific hazard is:

```text
h_i,c,g = N_i,c,g / E_i,c,g
```

where `N` is the number of target transition proxies and `E` is total exposure
in the source status, measured in hours. The corresponding probability for a
decision interval `delta` is:

```text
q_i,c,g(delta) = 1 - exp(-h_i,c,g * delta)
```

The default decision interval is five minutes. The estimator reports the raw
event count, exposure, hourly hazard, converted probability and a 95% Poisson
rate score interval. No pseudo-events or hidden smoothing are introduced.

## Temporal heterogeneity and fallback

Exposure is split in `Europe/Vilnius` local time into:

- weekday versus weekend;
- local hour `0..23`.

A local stratum is used only when it contains at least three target events and
positive exposure. Otherwise `estimate_for(...)` explicitly falls back to the
corresponding site-wide channel estimate. The three-event threshold is an
initial versioned engineering rule, not evidence that the local estimate is
stable. It prevents an empty or extremely sparse cell from being treated as a
certain zero transition probability.

## Role in assumption-driven simulation

The fitted baseline supplies `h_release,0` and `h_start,0`. The implemented
release response perturbs the first of them as follows:

```text
h_release,1(t) = h_release,0(t)
                 * exp(theta_release * effective_driver(t - tau))
```

Here `theta_release` and `tau` remain assumed scenario parameters. The final
driver is produced outside the response layer and will later contain applicable
rollout and intensity terms. A zero driver or `theta_release=0` exactly
reproduces the baseline transition process.

## Current-data status

The estimator is implemented and testable on synthetic qualified histories,
but the database audit dated 2026-10-08 found no site with the required seven
days of observations. Production fitting is therefore intentionally withheld
until the readiness assessment passes. This avoids converting a short demo
window into an apparently validated weekly behaviour model.
