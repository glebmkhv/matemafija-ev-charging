# Release response channel

Status: **implemented assumption-driven mechanism v1.0.0**.

The release response is the first implemented behavioural
response channel. The implementation is in `src/release_response.py` and
instantiates the policy-independent boundary defined in
`docs/response_contract.md`.

## 1. Scope

The channel modifies only the observable proxy transition:

```text
charging -> available
```

It does not claim to observe charging completion, cable disconnection,
post-charge idle time or the user's reason for leaving. It does not modify
`available -> charging`, equipment states, reservations or spatial demand.

## 2. Mathematical form

For entity `i` and evaluation time `t`:

```text
h_release,1(i,t)
    = h_release,0(i,t)
      * exp(theta_release * d_i(t - tau))
```

where:

- `h_release,0` is a statistically qualified baseline release hazard in
  `1/hour` from `transition_model.py`;
- `d_i` is the final external response driver in `EUR/min`;
- `theta_release` is an assumed non-negative sensitivity in `min/EUR`;
- `tau` is the assumed response delay in minutes.

The exponent is dimensionless. The probability over the baseline model's
decision interval `Delta` is:

```text
q_release,1 = 1 - exp(-h_release,1 * Delta)
```

This hazard form keeps the result non-negative and the converted probability in
`[0,1)`.

## 3. Interpretation

For `theta_release >= 0`:

- zero driver reproduces the baseline exactly;
- a positive driver increases the release hazard;
- a negative driver decreases it;
- larger driver values cannot produce a smaller release hazard.

`theta_release` remains `assumed`. Running many scenarios does not estimate it.
Results must use conditional language: *if release sensitivity equals this
value under this response form, the simulated release probability changes by
this amount*.

## 4. Driver and delay

The mechanism expects the driver named `effective_policy_adjustment`. It is now
produced by `src/policy_integration.py` as
`R_i(t) * lambda * OSA_raw_adjustment`. F1 remains a separate structured tariff
reference rather than being reduced to a scalar rate.

At time `t`, the implementation selects the latest driver point whose effective
time is no later than `t - tau`. It uses a piecewise-constant signal:

- future values are never used;
- values are not interpolated;
- if no delayed value exists, evaluation is rejected;
- a withheld policy decision is never converted to zero.

## 5. Output boundary

`ReleaseResponseResult` records evaluation and driver timestamps, driver value,
delay, sensitivity, baseline and adjusted hazards, the hazard multiplier,
baseline and adjusted decision-interval probabilities, model identities and
mandatory `simulated` provenance.

The mechanism does not draw a Bernoulli event and does not mutate system state.
Those operations belong to the later simulator engine and paired Monte Carlo
step.

## 6. Validation and numerical safety

Evaluation is rejected when the baseline is not a qualified `release_proxy`,
the specification differs from the canonical release contract, the driver is
invalid or absent at the delayed time, timestamps are duplicated, sensitivity
is negative/non-finite, or the exponent is outside `[-700,700]`.

A zero baseline hazard remains zero under every multiplier. The response model
does not invent releases where the fitted baseline contains no release process.

## 7. Explicit exclusions

This function itself does not calculate policy/adoption or draw a transition.
The separate accepted-start proxy is documented in `arrival_response.md`;
spatial redistribution, queue/idle inference and claims that the assumed
response is true in Vilnius remain excluded.
