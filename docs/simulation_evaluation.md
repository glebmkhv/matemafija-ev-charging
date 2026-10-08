# Paired scarcity evaluation of simulated projections

Status: **implemented v1.0.0**.

`src/simulation_evaluation.py` completes step 12 of the research plan. It
passes fixed and adaptive projections through the same canonical snapshot-level
scarcity definitions from `src/scarcity.py` and reports adaptive-minus-fixed
changes on matched timestamps.

## 1. Common evaluation path

For each Monte Carlo run:

```text
same baseline timestamps
        |
        +-- fixed projected A/C ----+
        |                            |
        +-- adaptive projected A/C -+--> canonical scarcity snapshot metrics
                                             |
                                             +--> paired changes
```

Both arms retain the source snapshot's reserved, non-operational and
indeterminate counts. Only the simulated `available` and `charging` partition
differs. Operational capacity and equipment state therefore remain matched.

## 2. Shared eligibility mask

A projected timestamp is eligible only when:

- the paired simulation point is comparison-eligible;
- effective operational capacity is positive;
- source observation coverage is present and meets the declared minimum.

The default minimum is `0.8`, matching the current scarcity layer. If a policy
decision or delayed driver was withheld, the timestamp is ineligible in both
arms. It is never interpreted as zero scarcity or zero policy effect.

## 3. Reported metrics

For each arm the evaluator reports:

- total, eligible and ineligible point counts;
- zero-availability point count;
- `zero_availability_snapshot_share`;
- `mean_availability_ratio`;
- `mean_operational_scarcity_ratio`.

Paired changes are always defined as:

```text
change = adaptive - fixed
```

Therefore, under the current objective:

- negative zero-availability-share change is favourable;
- positive mean-availability change is favourable;
- negative mean-operational-scarcity change is favourable.

When neither arm has eligible points, ratios and changes remain absent rather
than becoming zero.

## 4. Why episode metrics are withheld

The release-only runner makes independent one-step projections from each
baseline snapshot. It does not feed one projected state into the next timestamp
because the arrival-response channel has not yet been implemented.

Consequently, adjacent projected zero-availability points are not yet a
stateful simulated episode. Episode count and duration would overstate the
temporal meaning of the current model, so every result explicitly records:

```text
episode_metrics_applicable = false
```

The observed-data episode definitions remain unchanged. Simulated episode
metrics may be enabled only after the simulator produces coherent stateful
trajectories.

## 5. Provenance and claim boundary

All evaluated outcomes have `simulated` provenance and
`scenario_conditional` claim scope. The evaluator preserves the grid,
trajectory-generator and transition-model versions.

Permitted statement:

> Conditional on the declared release-response mechanism, the adaptive arm
> changed projected snapshot-level scarcity by this amount relative to paired
> F1.

Not permitted:

> The policy was observed to reduce queues, waiting time, post-charge idle or
> persistent real-world scarcity episodes.

Step 13 may aggregate the paired per-replication changes into uncertainty
intervals, robustness regions and minimum response thresholds without changing
these definitions.

