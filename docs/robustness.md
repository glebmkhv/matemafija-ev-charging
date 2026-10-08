# Robustness region and minimum tested response threshold

Status: **implemented v1.0.0**.

`src/robustness.py` completes step 13 of the research plan. It aggregates the
paired scarcity changes from Monte Carlo replications and identifies the part
of the declared assumption grid where improvement is statistically robust.

## 1. Primary metric and direction

The default primary metric is
`zero_availability_snapshot_share`. Alternative supported metrics are mean
availability and mean operational scarcity.

Every paired change is `adaptive - fixed`. A replication is an improvement
when:

```text
zero-availability or operational scarcity: change < -minimum_effect_size
mean availability:                         change >  minimum_effect_size
```

The inequality is strict. Equality is not counted as improvement. The default
effect margin is zero; a non-zero margin can require practical rather than
merely directional improvement.

## 2. Scenario-level uncertainty

For every `(lambda, theta_release, theta_arrival, delay)` cell the implementation reports:

- total, valid and missing replication counts;
- improvement count and empirical probability;
- Wilson confidence interval for the improvement probability;
- mean and median paired metric change;
- central empirical change interval at the selected confidence level.
- mean deferred-or-displaced accepted-start proxy count.

Missing metric values are excluded from the denominator and remain visible in
`missing_replication_count`. A scenario without valid replications has no
probability or effect estimate.

The Wilson interval is used instead of a normal approximation because the
outcome is binary per replication and probabilities near zero or one are
common.

## 3. Empirical success versus robust success

With the default specification:

```text
target improvement probability = 0.80
confidence level               = 0.95
minimum valid replications      = 20
```

`empirically_successful` means:

```text
observed improvement frequency >= 0.80
```

`robust_success` is deliberately stronger:

```text
valid replications >= 20
and Wilson lower bound >= 0.80
```

Thus a handful of successful draws cannot enter the robustness region. The
region is the explicit list of scenario IDs satisfying the stronger rule.

## 4. Minimum response threshold

For each tested `(lambda, theta_arrival, delay)` combination, the implementation
selects the smallest tested `theta_release` whose scenario is robust. The
output is named:

```text
minimum_tested_theta_release
```

It is a grid-identified threshold, not an interpolated continuous estimate. If
no tested sensitivity is robust, the threshold remains absent with
`identified_on_grid = false`. The result must not be reported as “the true user
price elasticity”.

## 5. Interpretation boundary

The result remains `simulated` and `scenario_conditional`:

> Conditional on this baseline path, OSA-v1 policy, release-response form and
> parameter grid, these cells improve the selected scarcity metric with a
> sufficiently high and statistically supported simulation frequency.

It does not establish that Vilnius users have the assumed sensitivity. The
current interval captures stochastic release-transition uncertainty
conditional on one supplied baseline path. To describe uncertainty across
historical baseline paths, the entire pipeline must be repeated for multiple
independently generated block-bootstrap paths; those results must not yet be
silently pooled by this v1 runner.

The result preserves the complete grid (including root seed and replication
count), trajectory-generator version, transition-model version, scarcity
coverage threshold and evaluation version for reproducibility.

No queue, waiting-time, post-charge-idle or causal real-world claim is enabled.
