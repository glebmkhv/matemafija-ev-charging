# F1 + OSA + adoption + release-response integration

Status: **implemented v1.0.0**.

The integration layer in `src/policy_integration.py` connects the factual OCPI
tariff reference, OSA-v1 raw adjustment, rollout/intensity design and the
release-response driver without collapsing their provenance or units.

## 1. Composition

For entity `i` and time `t`:

```text
d_i(t) = R_i(t) * lambda * delta_p_raw(i,t)
```

where:

- `delta_p_raw` is the OSA-v1 result in `EUR/min`;
- `lambda` is policy intensity in `[0,1]`;
- `R_i(t)` is the binary rollout state;
- `d_i(t)` is `effective_policy_adjustment`, the driver consumed by the release
  response.

Coverage `kappa` is recorded from the explicit eligible/treated populations. It
does not multiply the per-entity adjustment: coverage determines who is treated,
while `R_i(t)` determines whether this particular entity is active.

## 2. Component-aware F1 treatment

F1 is a structured OCPI tariff and may contain `ENERGY`, `TIME`,
`PARKING_TIME` and `FLAT` components. It is therefore incorrect to describe the
whole factual tariff as one `EUR/min` scalar.

The integration preserves the observed F1 tariff key, revision, currency and
component types. The adaptive adjustment is represented as a separate
counterfactual `TIME` component:

```text
adaptive_TIME_rate_EUR_per_hour = 60 * d_i(t)
```

The original F1 components are not overwritten or averaged with DATEX.

## 3. Catalogue replay versus monetary replay

A structured `ObservedTariff` is sufficient to compose and display the
counterfactual tariff mechanism. A calculated F1 monetary total is optional and
requires observed Session/CDR/meter usage.

Even when a factual F1 total exists, the integration does not add the adaptive
rate to it without an observed duration over which the adjustment applied. The
field `counterfactual_total` therefore remains absent with reason:

```text
requires_observed_adjustment_duration
```

This permits a real-data demonstration using the current tariff catalogue while
preventing a fabricated user bill or revenue claim. VAT treatment of a future
adaptive component must also be approved before monetary billing.

## 4. Status propagation

### `active`

F1 and OSA are valid, rollout is active, lambda is positive and OSA emits a
positive raw adjustment.

### `inactive`

Inputs are valid but the effective adjustment is zero because:

- rollout is inactive;
- lambda is zero;
- OSA is valid but inactive.

An inactive composition emits a valid zero driver. Under the release model this
exactly reproduces the baseline hazard.

### `withheld`

No driver is emitted when:

- the OCPI tariff reference is unavailable;
- the tariff currency is not EUR;
- OSA is withheld.

Withheld never becomes a zero driver.

## 5. Provenance chain

```text
OCPI F1 tariff                         observed/reconstructed
OSA signal and raw adjustment         policy_defined
lambda, kappa and R_i(t)               policy_defined
effective_policy_adjustment            policy_defined
theta_release and delay                assumed
adjusted release hazard/probability    simulated
```

The integration test verifies the complete deterministic chain through the
release-response result. It does not yet draw state transitions.

## 6. Explicit exclusions

This layer itself does not draw stochastic transitions. The downstream paired
Monte Carlo runner is now implemented in
[`simulation_grid.md`](simulation_grid.md). Scarcity metric comparison,
robustness regions, arrival response and spatial redistribution remain later
project steps.
