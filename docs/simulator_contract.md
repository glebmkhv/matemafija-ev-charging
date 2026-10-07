# Common generalized simulator contract

Status: **draft v0.3**. This contract defines inputs, events, policies, outputs
and permitted claims before implementation of a simulation engine.

The contract is represented in code by `src/simulation_contract.py`. The fixed
tariff replay is implemented separately in `src/fixed_policy.py`; the adaptive
formula remains to be agreed.

Before constructing a run, site-level eligibility must be checked against
`docs/baseline_readiness.md`. `assumption_driven_counterfactual` requires both
the transition-model and factual F1 tariff gates; a merely descriptive history
is not silently promoted into a fitted baseline model.

## 1. Purpose

The common generalized simulator is one execution environment into which fixed
and adaptive policies are inserted. Both policies must receive the same:

- physical structure;
- observed timeline;
- observed Session/CDR/meter periods when monetary totals are compared;
- reconstruction rules;
- statistically qualified derivative inputs;
- evaluation window;
- event ordering;
- output definitions.

Only the policy specification may differ. This makes the comparison paired and
prevents improvements from being caused by different source data.

The contract distinguishes factual replay, assumption-driven stress testing
and a future empirically validated counterfactual. These modes must never be
collapsed into one generic "simulation" result.

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

### 2.2 `assumption_driven_counterfactual`

This is the project stress-testing mode. It starts from the real reconstructed
baseline and permits a versioned hypothetical price-response mechanism to alter
the state trajectory. Its response parameters have `assumed`, not `estimated`,
provenance.

It answers conditional questions such as:

> If the release response has the specified functional form, sensitivity and
> delay, how do the simulated scarcity metrics differ from the F1 baseline?

It may report simulated state and scarcity differences, robustness regions and
minimum response thresholds. It may not present those values as observed,
estimated from Vilnius behaviour or causally predicted. Every result has
`claim_scope = scenario_conditional` and carries a visible assumption
disclosure plus response-model identity/version.

The mode requires a deterministic random seed so paired policy runs are
reproducible. A future experiment runner will additionally use common random
numbers between matched scenarios.

### 2.3 `validated_counterfactual`

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
3. Every input carries observed, reconstructed, estimated, policy-defined,
   assumed or simulated provenance.
4. Required derivative statistics must be statistically qualified.
5. Ineligible snapshots never become evidence of scarcity.
6. A collection gap never becomes zero demand or continuous occupancy.
7. `CHARGING` is not automatically continuous energy transfer.
8. Zero availability is not a physical queue.
9. Observed replay cannot emit simulated behaviour or released capacity.
10. An assumed parameter is never relabelled as an empirical estimate.
11. Assumption-driven output is always scenario-conditional, never a causal
    prediction.
12. Equipment-failure transitions may not be modified by a price-response
    assumption unless a separate, defensible mechanism is explicitly approved.
13. All contracts, policies, response models, estimators and structures are
    versioned.

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

### 5.1 Observed session input for tariff comparison

`ObservedChargingSession` and `ObservedChargingPeriod` carry connector-level,
timezone-aware Session/CDR/meter quantities: energy, charging time, parking
time and average power. Their provenance must be `observed`. Status snapshots
cannot be converted into these quantities. Consequently a fixed/adaptive
monetary comparison is withheld until this optional input is supplied, while
the capacity-timeline replay remains available.

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

The baseline transition process is fitted by `src/transition_model.py` under
the rules in [`transition_model.md`](transition_model.md). It supplies
site-specific `charging_start_proxy` and `release_proxy` hazards, not vehicle
arrivals, queues, charge-completion times or post-charge idle durations.

## 7. Policy input

`PolicySpecification` contains:

- policy ID and version;
- `fixed` or `adaptive` kind;
- currency;
- decision interval;
- explicit parameters;
- names of required derivative statistics.

The sole fixed baseline is the factual, component-aware OCPI tariff assigned to
the connector. Matched DATEX pricing is retained as corroborating evidence.
Its applicability and withholding rules are specified in
[`fixed_policy.md`](fixed_policy.md).

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

### 7.1 Policy adoption input

`PolicyAdoptionSpecification` prevents three different ideas from being hidden
behind one parameter.

#### Price intensity

`price_intensity_lambda` is the strength of the adaptive price adjustment:

```text
0 <= lambda <= 1
p_i(t) = p_F1,i(t) + R_i(t) * lambda * adaptive_price_delta_i(t)
```

`lambda = 0` preserves the F1 price even when an entity belongs to the rollout;
`lambda = 1` applies the complete adaptive adjustment. Lambda is not coverage
and not elapsed rollout time.

#### Coverage

The eligible and treated entity populations are explicit, unique lists at one
declared unit: `site` or `evse`. Target coverage is derived rather than entered:

```text
kappa = number_of_treated_entities / number_of_eligible_entities
```

This prevents a supplied `kappa` from contradicting the actual rollout set.
Treated entities must be a subset of eligible entities, and every entity must
exist in the supplied `SiteStructure`.

The current `SimulationRequest` contains one `SiteStructure`. Consequently,
site-level coverage is currently either zero or one within a request; fractional
coverage is available at EVSE level. A later network experiment wrapper must
hold multiple validated site requests before cross-station `kappa` is used. The
single-site contract must not pretend to represent city-wide partial coverage.

#### Rollout state

Each treated entity has one or more non-overlapping, timezone-aware activation
windows. The time-dependent rollout indicator is:

```text
R_i(t) = 1  if t lies in an activation window for entity i
         0  otherwise
```

Windows are half-open: `active_from <= t < active_until`; an omitted end means
continued activation. Active coverage at a given time is derived as:

```text
kappa(t) = sum_i R_i(t) / number_of_eligible_entities
```

The adoption design has `policy_defined` provenance. Counterfactual modes
require it even for a baseline arm (`lambda = 0` or empty treated set), ensuring
that paired runs differ through explicit, auditable inputs.

### 7.2 Response-model input

`AssumptionDrivenResponseSpecification` is deliberately independent of the
eventual adaptive price formula. It defines how a supplied price difference may
hypothetically change selected state transitions. It contains:

- model ID and version;
- explicit functional form;
- one or more response channels, initially `release` and later `start`;
- exact affected transitions, for example `charging_to_available`;
- complete parameter values and a unit for every parameter;
- response delay;
- the simulated outcomes the mechanism is allowed to support;
- mandatory `assumed` provenance.

A proposed initial form is:

```text
logit(q_release,1)
    = logit(q_release,0)
    + theta_release * price_intensity * adaptive_price_delta(t - delay)
```

This equation is not yet an implemented or approved behavioural model. The
contract merely provides a safe slot for it. `theta_release` cannot be described
as estimated until it has an identified evidence source and estimator.

`BehaviouralResponseSpecification` remains reserved for validated
counterfactual execution. It requires evidence metadata, a validation report,
supported outcomes and explicit validation for Vilnius. A request must contain
exactly the response type required by its execution mode; assumed and validated
responses cannot coexist.

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

- `response_assumption_applied`: records the exact assumed mechanism and
  parameters used at an evaluation point;
- `simulated_state_transition`: a state transition generated under a response
  model;
- `counterfactual_behaviour_change`;
- `counterfactual_capacity_release`.

`response_assumption_applied` has assumed provenance and is legal only in
assumption-driven mode. State-changing counterfactual events have simulated
provenance and are forbidden in observed replay.

## 9. Event ordering

For a single UTC timestamp, the eventual engine must use a deterministic order:

1. ingest the observed snapshot;
2. update reconstructed observable context;
3. emit observed transition proxies whose upper bound is this timestamp;
4. evaluate rollout state `R_i(t)` and active coverage `kappa(t)`;
5. evaluate the policy if its interval is due;
6. compose F1 with `R_i(t) * lambda * adaptive_price_delta`;
7. emit the policy decision;
8. in assumption-driven mode, record and apply the assumed response model;
9. in validated counterfactual mode, apply the validated response model;
10. generate any permitted simulated state transition;
11. record outputs.

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

Every counterfactual result also contains `AdoptionResultMetadata`: adoption
ID/version and unit, lambda, target kappa, and minimum/maximum active coverage
observed across the run. Active coverage may not exceed target coverage. This
metadata is part of the result itself rather than being recoverable only from a
request or log.

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

### 11.3 Assumption-driven outputs

Permitted outputs are explicitly simulated or scenario-conditional:

- `simulated_availability_change`;
- `simulated_zero_availability_share_change`;
- simulated scarcity-episode count and duration changes;
- simulated release/start transition changes;
- improvement frequency across repeated runs;
- uncertainty intervals across baseline paths and stochastic replications;
- robustness regions in the declared assumption space;
- minimum response thresholds under the declared functional form.

Names such as `capacity_released_by_fee`, `users_changing_behaviour`,
`waiting_time_reduction` and `queue_length_reduction` remain forbidden because
without qualification they read as causal or observed claims. Each result must
identify the assumed model and include a human-readable disclosure.

### 11.4 Validated-counterfactual-only outputs

Each causal output must be listed in the validated behavioural-response model's
`supported_outcomes`. Unsupported outcomes remain forbidden even in
counterfactual mode.

## 12. Fixed versus adaptive comparison protocol

One comparison unit consists of matched requests with:

- the same site structure and version;
- the same ordered observed timeline;
- the same training and evaluation windows;
- the same qualified derivative statistics;
- the same decision interval;
- the same baseline-generation method and random seed for stochastic runs;
- the same response model when policies are compared;
- only the intended experimental dimension may differ: policy parameters,
  price intensity, coverage set or rollout schedule. All other adoption fields
  remain matched.

Results are joined by site and evaluation timestamp. Missing or withheld
decisions remain explicit.

Replay comparison reports differences in mechanism outputs. It must state:

> This comparison shows how two pricing rules would have evaluated the same
> observed history. It does not estimate how users would have responded.

Assumption-driven comparison must state:

> This result is conditional on the declared hypothetical response model and
> parameters. It is a stress-test scenario, not an observed or validated causal
> effect.

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

Assumption-driven execution can answer a narrower question:

- under which assumed response mechanisms simulated availability improves;
- how strong an assumed response must be;
- whether improvement persists across baseline and stochastic uncertainty.

It cannot answer whether the assumed response is true. A predictive or causal
claim that availability will improve requires either:

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
- adoption ID/version, unit, lambda, derived target/active coverage and complete
  rollout windows;
- execution mode and claim scope;
- assumed response model, complete parameters, units and disclosure;
- validated response evidence and report when applicable;
- timezone and decision interval;
- qualification thresholds;
- behavioural-response version when applicable;
- software revision;
- deterministic seed if future simulation uses randomness.

## 15. Decisions required before engine implementation

1. Agree with the mathematical-model author whether observable sustained
   scarcity replaces queue and post-charge idle in the MVP.
2. Approve an adaptive signal formula.
3. Approve fee floor, cap and recalculation interval.
4. Decide whether adaptive decisions require statistically qualified historical
   baselines or only current qualified snapshots.
5. Define withheld behaviour and recovery after data gaps.
6. Approve the exact replay evaluation metrics.
7. Define the first release-response functional form and assumption grid.
8. Decide what evidence could promote an assumed parameter to an estimate and
   eventually unlock validated counterfactual mode.
