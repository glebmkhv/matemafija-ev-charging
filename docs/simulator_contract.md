# Common generalized simulator contract

Status: **draft v0.1**. This contract defines inputs, events, policies, outputs
and permitted claims before implementation of a simulation engine.

The contract is represented in code by `src/simulation_contract.py`. It does
not yet implement fixed or adaptive policy formulas.

## 1. Purpose

The common generalized simulator is one execution environment into which fixed
and adaptive policies are inserted. Both policies must receive the same:

- physical structure;
- observed timeline;
- reconstruction rules;
- statistically qualified derivative inputs;
- evaluation window;
- event ordering;
- output definitions.

Only the policy specification may differ. This makes the comparison paired and
prevents improvements from being caused by different source data.

For the data-grounded MVP, the safest form of the common model is an observed
timeline replay and policy-evaluation engine. It is not yet a synthetic model
of individual vehicles.

## 2. Execution modes

### 2.1 `observed_replay`

The engine replays actual capacity snapshots and reconstructed transitions in
chronological order. At every policy evaluation point, fixed or adaptive policy
receives the same observable context and emits a decision.

This mode can answer:

- is the policy formula implemented correctly;
- does it activate only on qualified evidence;
- how frequently would it activate;
- what rate would it display;
- is the response monotonic and bounded;
- how different are fixed and adaptive decisions on the same history.

It cannot answer:

- whether a driver would leave earlier;
- whether capacity would be released;
- whether waiting would fall;
- whether revenue, welfare or user behaviour would change.

Observed replay has `claim_scope = mechanism_only`.

### 2.2 `validated_counterfactual`

This future mode permits policy decisions to alter the state trajectory. It is
disabled unless a behavioural-response specification contains:

- model identity and version;
- evidence source;
- validation report;
- outcomes it can support;
- explicit validation for the Vilnius context.

An external-city estimate is not sufficient merely because it is public. Its
transferability must be validated.

Only this mode may have `claim_scope = counterfactual_effect`.

## 3. Non-negotiable invariants

1. Raw OCPI/DATEX observations are never rewritten by a policy run.
2. Fixed and adaptive policies use an identical input timeline.
3. Every input carries observed, reconstructed, estimated or policy-defined
   provenance.
4. Required derivative statistics must be statistically qualified.
5. Ineligible snapshots never become evidence of scarcity.
6. A collection gap never becomes zero demand or continuous occupancy.
7. `CHARGING` is not automatically continuous energy transfer.
8. Zero availability is not a physical queue.
9. Observed replay cannot emit simulated behaviour or released capacity.
10. All contracts, policies, estimators and structures are versioned.

## 4. Structural input

`SiteStructure` defines what physical/source-native system is being evaluated:

- `ocpi_location_key`;
- `structure_version`, normally tied to a complete snapshot or exported
  structure artifact;
- local timezone;
- coordinates when available;
- the EVSE identities belonging to the location;
- connector count per EVSE;
- maximum electrical power when known.

The MVP uses source-native OCPI locations. Canonical OCPI/DATEX sites may be
added later only with explicit mapping confidence, cardinality and review
status.

Connector count is metadata and is not assumed to equal simultaneous charging
capacity. EVSE is the default capacity unit.

## 5. Observed timeline input

Each `ObservedSystemState` corresponds to a successful complete OCPI snapshot
after reconstruction by `flow.py`.

Required fields include:

- observation timestamp in UTC;
- offered EVSE count;
- available, charging and reserved counts;
- non-operational and indeterminate counts;
- effective operational capacity;
- availability ratio;
- occupancy proxy;
- zero-availability evidence;
- valid observation coverage.

The contract checks the partition:

```text
effective_operational_capacity
    = available + charging + reserved

offered_evse_count
    = effective_operational_capacity
    + non_operational
    + indeterminate
```

Timeline timestamps must be timezone-aware, unique and increasing.

## 6. Derivative-statistic input

A policy may declare named required statistics. Each
`DerivedStatisticInput` contains:

- canonical variable name;
- numeric value and unit;
- estimator version;
- training-window bounds;
- statistical qualification flag;
- confidence interval when qualified.

The request is rejected when a required statistic is missing, duplicated or
unqualified. A policy that only uses current observable state may require no
derivative statistic.

The data used to evaluate a policy must not also be silently used to train a
required parameter when this would introduce look-ahead bias. Future
experiments must define training and evaluation windows separately.

## 7. Policy input

`PolicySpecification` contains:

- policy ID and version;
- `fixed` or `adaptive` kind;
- currency;
- decision interval;
- explicit parameters;
- names of required derivative statistics.

Possible fixed baselines remain separate:

1. `observed_tariff_replay`: reproduce a structured operator tariff where it is
   available;
2. `constant_test_fee`: apply an explicitly chosen constant prototype rate.

They must not share one ambiguous label.

An adaptive policy must eventually specify:

- activation evidence;
- signal formula and version;
- mapping from signal to rate;
- floor and cap;
- recalculation interval;
- behaviour on ineligible observations;
- hysteresis/cooldown, if any.

The colleague-proposed queue/post-charge-idle SII is not inserted into this
contract as a valid data input because its required variables are unavailable.
It remains a proposal to be reviewed separately.

## 8. Event catalogue

### Observed/reconstructed events

- `observed_snapshot`: one valid capacity snapshot;
- `observed_status_transition`: a bounded status transition proxy.

### Policy events

- `policy_evaluation`: the policy is evaluated on the current context;
- `policy_action`: the policy emits a rate or no-action decision.

Policy events are policy-defined outputs. They do not alter the observed
timeline in replay mode.

### Counterfactual events

- `counterfactual_behaviour_change`;
- `counterfactual_capacity_release`.

These events have simulated provenance and are forbidden in observed replay.

## 9. Event ordering

For a single UTC timestamp, the eventual engine must use a deterministic order:

1. ingest the observed snapshot;
2. update reconstructed observable context;
3. emit observed transition proxies whose upper bound is this timestamp;
4. evaluate the policy if its interval is due;
5. emit the policy decision;
6. in validated counterfactual mode only, evaluate behavioural response;
7. record outputs.

Tie-breaking and missing-snapshot behaviour must be identical for fixed and
adaptive policies.

## 10. Policy-decision output

Each future policy decision should contain at least:

- evaluation timestamp;
- policy ID/version;
- action status: active, inactive or withheld;
- evidence eligibility;
- signal name/version/value;
- rate and unit;
- floor/cap application;
- reason code;
- exact input snapshot/run identity.

`withheld` is mandatory when required evidence is unavailable. It must not be
silently converted to a zero rate.

## 11. Evaluation outputs

### 11.1 Allowed in observed replay

Data-quality and evidence outputs:

- evaluated and withheld snapshot counts;
- evidence coverage;
- observed availability and scarcity metrics;
- collection-gap counts.

Mechanism outputs:

- policy evaluation count;
- activation count/share;
- rate time series;
- mean, median, maximum and variability of displayed rate;
- number of rate changes;
- activation during qualified zero availability;
- false activation when qualified availability is positive;
- action on ineligible evidence, which should be zero;
- cap/floor activation count;
- fixed/adaptive decision difference on matched timestamps.

These outputs answer `does the policy mechanism work as specified?`

### 11.2 Forbidden in observed replay

- capacity released by fee;
- number of users changing behaviour;
- queue reduction;
- waiting-time reduction;
- additional served vehicles;
- causal revenue attributable to behaviour change;
- welfare improvement.

### 11.3 Counterfactual-only outputs

Each causal output must be listed in the validated behavioural-response model's
`supported_outcomes`. Unsupported outcomes remain forbidden even in
counterfactual mode.

## 12. Fixed versus adaptive comparison protocol

One comparison unit consists of two validated requests with:

- the same site structure and version;
- the same ordered observed timeline;
- the same training and evaluation windows;
- the same qualified derivative statistics;
- the same decision interval;
- different policy ID/version and parameters only.

Results are joined by site and evaluation timestamp. Missing or withheld
decisions remain explicit.

Replay comparison reports differences in mechanism outputs. It must state:

> This comparison shows how two pricing rules would have evaluated the same
> observed history. It does not estimate how users would have responded.

## 13. Answering the two project questions

### Does the model work?

Observed replay can answer the engineering version:

- inputs are accepted or rejected correctly;
- activation follows the agreed scarcity rule;
- rates are monotonic, stable and bounded;
- no action occurs on ineligible evidence;
- outputs are reproducible.

### Is there a visible effect?

Observed replay can show a visible difference in **policy decisions**, not a
visible behavioural or capacity effect.

A claim that availability improved requires either:

- a validated counterfactual behavioural model;
- a controlled pilot/intervention;
- a defensible quasi-experimental design using real policy changes.

## 14. Reproducibility metadata

Every request/result pair must preserve:

- contract version;
- database snapshot or query-window identity;
- structure version;
- interval/flow/scarcity estimator versions;
- policy version and complete parameters;
- timezone and decision interval;
- qualification thresholds;
- behavioural-response version when applicable;
- software revision;
- deterministic seed if future simulation uses randomness.

## 15. Decisions required before engine implementation

1. Select one or both fixed baselines.
2. Agree with the mathematical-model author whether observable sustained
   scarcity replaces queue and post-charge idle in the MVP.
3. Approve an adaptive signal formula.
4. Approve fee floor, cap and recalculation interval.
5. Decide whether adaptive decisions require statistically qualified historical
   baselines or only current qualified snapshots.
6. Define withheld behaviour and recovery after data gaps.
7. Approve the exact replay evaluation metrics.
8. Decide what evidence could unlock counterfactual mode.
