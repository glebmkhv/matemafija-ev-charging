# Release response channel

Status: **implemented v1.0.0 compatibility profile and typed v2.0.0 profile**.

The release response is the first implemented behavioural
response channel. The implementation is in `src/release_response.py` and
instantiates the policy-independent boundary defined in
`docs/response_contract.md`.

The original scalar profile remains available without changed semantics. The
v2 profile adds separate typed price and optional release-credit terms; it does
not reinterpret historical v1 results.

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
spatial allocation is a separate downstream assumption layer; queue/idle
inference and claims that the assumed response is true in Vilnius remain
excluded.

## 8. Typed v2 profile

The executable v2 form is:

```text
h_release,2 = h_release,0 * exp(
    theta_release_price * delayed_origin_price_contribution_rate
  + theta_release_credit * delayed_release_credit_offer
)
```

The terms retain different units:

- price signal: `EUR/min`, sensitivity: `min/EUR`;
- release-credit signal: integer `MCU`, sensitivity: `1/MCU`;
- each term has its own non-negative integer-minute delay.

`TypedResponseSignalPoint` records signal identity, unit, state, source event,
timestamp, contract version and provenance. Price signals require
`policy_defined` provenance; release-credit offers require `simulated`
provenance. Signal states are `available`, `not_applicable` and `withheld`.
Only an available signal has a numeric value.

The result reports price and credit exponent components separately, as well as
their total, multiplier, hazards and probabilities. This makes it possible to
audit which assumed mechanism changed the transition.

## 9. Initial credit applicability

The current allocation contract funds alternative-site credits, not a reward
for releasing an occupied EVSE. Consequently the initial production scenario
uses:

```text
release_credit_applicable = false
theta_release_credit = 0
```

The executable optional term exists for a future explicitly approved and
funded release-credit policy. An active credit signal cannot be silently ignored
by a profile marked non-applicable, and an alternative-site offer cannot be
copied into this channel.

## 10. Compatibility and validation

`typed_price_signal_from_v1` maps the existing policy-integration driver to the
canonical v2 price name while preserving value, timestamp and provenance.
Withheld remains withheld.

The v2 implementation additionally rejects:

- negative price/credit signals or sensitivities;
- fractional MCU;
- unit, name, provenance or entity mismatch;
- duplicate signal timestamps;
- missing delayed signals;
- non-applicable credit profiles carrying active credit;
- withheld signals treated as numeric zero;
- unsafe exponential values.

The function remains deterministic and does not draw or mutate state.
