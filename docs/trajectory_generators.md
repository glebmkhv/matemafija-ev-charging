# Baseline trajectory generators

The common simulator has two baseline trajectory generators, implemented in
`src/trajectory.py` and versioned as `1.0.0`.

They generate the policy-independent path onto which fixed or adaptive policy
logic may later be applied. Neither generator contains a price, rollout or
behavioural-response mechanism.

## 1. Observed path

`generate_observed_path(...)` performs exact deterministic replay:

- timestamps are unchanged;
- every capacity-state vector is unchanged;
- ordering and missingness are unchanged;
- point provenance remains `reconstructed`;
- no random seed or sampled-block metadata is permitted.

This generator is appropriate for `observed_replay` and for checking that a
pricing mechanism can consume the factual timeline. It does not create an
alternative system history.

## 2. Local-day block bootstrap

`generate_local_day_block_bootstrap(...)` samples whole Vilnius local-calendar
days with replacement. Weekdays are sampled only from qualified weekdays and
weekends only from qualified weekends.

The complete site snapshot vector is moved as one object. Available, charging,
reserved, non-operational and indeterminate components are never bootstrapped
independently. Consequently each selected block preserves:

- the observed within-day sequence and autocorrelation;
- simultaneous relationships among capacity variables;
- zero-availability and data-quality patterns;
- the physical capacity partition present in every source snapshot.

Dependence across day boundaries is not preserved. This limitation is explicit
and may later motivate multi-day blocks if sufficient history is collected.

## 3. Qualified source blocks

A bootstrap run requires `historical_profile_ready=true`. This prevents a few
apparently complete days from bypassing the seven-day project readiness gate.

By default, an individual source day additionally requires:

- at least 80% of the observations expected at the five-minute cadence;
- at least 80% eligible scarcity snapshots relative to that same denominator;
- a normal 24-hour local day.

Partial first/last collection days and DST transition days are excluded. A
target horizon containing a 23- or 25-hour DST day is currently rejected rather
than silently distorted. A dedicated DST block rule can be added in a later
version.

The generator fails if the requested target horizon needs a weekday/weekend
pool that does not exist. It never substitutes a weekday for a weekend.

## 4. Time mapping and provenance

For every generated point the artifact stores both:

- `trajectory_time_utc`: its time in the generated path;
- `source_observation_time_utc`: the exact observation from which the state was
  copied.

Sampled-block metadata records source and target local dates, day type, point
count and both coverage ratios. Bootstrap points have `simulated` provenance,
while their nested source states retain `reconstructed` provenance.

## 5. Reproducibility and paired comparison

Bootstrap sampling uses a required non-negative random seed. Identical inputs
and seed produce the same sequence of source blocks. Later paired fixed/adaptive
experiments must share the same generated baseline trajectory and seed; policy
effects must not be confounded with different resampled days.

## 6. Current-data status

Exact observed-path replay is available now. The block-bootstrap implementation
is complete and tested, but the database audit dated 2026-10-08 found no site
with `historical_profile_ready=true`. Real bootstrap generation is therefore
withheld until the collection window passes the readiness gate.

This step produces baseline variability only. It does not assert or simulate
how users react to a new price.
