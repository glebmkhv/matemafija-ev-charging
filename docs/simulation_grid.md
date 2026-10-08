# Paired simulation grid and Monte Carlo protocol

Status: **implemented v1.0.0**.

`src/simulation_grid.py` implements step 11 of the research plan: a seeded,
paired experiment over the release-only assumption-driven counterfactual. It
does not introduce an arrival response, queue, post-charge idle time or spatial
redistribution.

## 1. Scenario grid

The runner evaluates the Cartesian product

```text
lambda x theta_release x response_delay_minutes x replication
```

where:

- `lambda` is the intensity of the OSA-v1 adjustment in `[0,1]`;
- `theta_release` is the non-negative assumed release sensitivity;
- `response_delay_minutes` selects the policy driver at `t - tau`;
- `replication` is a repeated stochastic draw with a recorded seed.

Coverage and rollout remain properties of the supplied adoption specification;
they are not conflated with `lambda`. Every scenario records all three response
coordinates in a stable scenario ID.

## 2. Paired common-random-number design

For replication `r`, the seed is:

```text
replication_seed = root_seed + r
```

The generator is reset to that seed for every scenario. Point-level draws are
consumed even if a particular scenario later withholds that point, so differing
delay warm-up periods cannot shift the random stream. At a time point, the same
uniform draw is compared with the fixed probability `q0` and adaptive
probability `q1` for each charging EVSE. Consequently:

- fixed and adaptive arms share the same stochastic noise;
- scenario points share the same replication-level random stream;
- `lambda = 0` or `theta_release = 0` reproduces the fixed arm exactly;
- when a positive OSA signal makes `q1 >= q0`, adaptive releases cannot be
  fewer than fixed releases within the paired point.

This variance-reduction design makes differences attributable to declared
policy/response parameters rather than independent random draws.

## 3. Projection semantics

Each trajectory timestamp is a **one-step conditional projection** from the
same supplied baseline snapshot. For source counts `A(t)` and `C(t)`:

```text
A_fixed'(t)    = A(t) + releases_fixed(t)
C_fixed'(t)    = C(t) - releases_fixed(t)
A_adaptive'(t) = A(t) + releases_adaptive(t)
C_adaptive'(t) = C(t) - releases_adaptive(t)
```

Operational capacity is conserved in both arms. A projected state is not fed
into the next timestamp. This is deliberate: cumulative evolution would need
an arrival mechanism to replace accepted demand and is outside the release-only
MVP. Results must therefore be called conditional projections or a policy
stress test, not a full demand forecast.

Observed-path and block-bootstrap generators are both accepted upstream. Fixed
and adaptive arms always consume the identical generated path, transition
model, OSA decisions, F1 tariff and rollout design.

## 4. Eligibility and withholding

A point is withheld rather than coerced to zero when:

- F1/OSA composition withholds the policy driver; or
- no driver observation exists at or before `t - tau`.

Withheld points contain no release probabilities, draws, projected counts or
effective adjustment. This keeps missing signal history distinct from a valid
zero adjustment.

## 5. Current outputs

Every run records:

- scenario coordinates, replication index and seed;
- source available/charging counts;
- baseline and adjusted release probabilities;
- paired fixed/adaptive release counts;
- paired projected available/charging counts;
- the effective policy adjustment;
- eligible and withheld counts;
- total fixed, adaptive and additional releases.

All projected outcomes have `simulated` provenance. `theta_release` and delay
remain `assumed`; `lambda`, rollout and tariff adjustment remain
`policy_defined`; the baseline transition estimate remains `estimated`.

Release totals are diagnostic outputs, not the final policy score. Step 12
must evaluate both arms with the same existing scarcity definitions. Step 13
will aggregate those paired metric differences into uncertainty intervals,
robustness regions and a minimum response threshold.

## 6. Claim boundary

Permitted:

> Under this declared release-response sensitivity, delay, rollout and policy
> intensity, the adaptive arm changes these conditional simulated outcomes
> relative to paired F1.

Not permitted:

> Vilnius users will respond this way, or the policy has been shown to reduce
> real queues, waiting time or post-charge idle time.
