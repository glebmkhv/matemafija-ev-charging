# Generalized policy-independent response contract

Status: **approved contract v2.0; typed-vector implementation pending**.

This document completes step 7 of the credit-circulation plan. It generalizes
the implemented scalar price-response boundary without changing the existing
v1 release and charging-start code. Steps 8--10 will implement the v2 profiles.

The contract answers one question: given a qualified baseline process, a set of
policy outputs and explicit behavioural assumptions, how may the simulator
produce a conditional transition or choice quantity? It does not decide the
policy, allocate credits, estimate Vilnius behaviour or mutate system state.

## 1. Required separation

```text
estimated baseline process       policy-defined signals
hazard / outside option          price / credit / eligible choice set
                 \               /
                  typed response boundary
             assumed sensitivities and delays
                            |
            simulated hazards or choice probabilities
                            |
                    paired simulator draw
```

The response layer must not:

- read OCPI/DATEX or calculate scarcity;
- calculate F1, OSA, contribution, pool balance or offer amount;
- apply price intensity, coverage or rollout a second time;
- add an ineligible receiver to the frozen choice set;
- treat an offer as issued or redeemed credit;
- draw random events or mutate EVSE, receiver-capacity or ledger state;
- label assumed coefficients as correlations, elasticities or estimates.

This makes the response contract policy-independent: any future policy may
produce a compatible typed signal, while its formula and provenance remain
outside the behavioural mechanism.

## 2. Typed response bundle

One `GeneralizedResponseBundle` is identified by:

```text
(scenario_id, replication_id, choice_opportunity_id, evaluation_time_utc)
```

It contains three non-interchangeable profiles:

| Profile | Scope | Output |
| --- | --- | --- |
| `origin_release_v2` | one charging origin entity | adjusted `charging -> available` hazard |
| `origin_start_v2` | one available origin entity | adjusted `available -> charging` hazard |
| `receiver_choice_v1` | one immutable eligible choice set | normalized outside/origin/receiver probabilities |

Each signal carries its canonical name, value, unit, scope identity, effective
UTC timestamp, provenance, source event ID and contract version. Equal numeric
values with different names or units are not substitutable.

### Signal availability

Every declared signal has exactly one state:

- `available`: a finite value exists and may enter the model;
- `not_applicable`: the versioned profile does not use this signal;
- `withheld`: the signal should exist but its evidence or upstream contract is
  invalid; the affected profile cannot run.

`not_applicable` is not numeric zero. `Withheld` is never converted to zero.
An available zero means that the applicable mechanism supplies no intervention
at that instant and participates in the identity-at-zero test.

## 3. Canonical typed signals

| Signal | Unit | Scope | Source and provenance | Permitted use |
| --- | --- | --- | --- | --- |
| `origin_price_contribution_rate` | `EUR/min` | origin/time | effective OSA/adoption contribution component; `policy_defined` | release and origin-start profiles |
| `release_credit_offer` | integer `MCU` | origin/time | a future explicitly allocated release offer; `policy_defined` rule, `simulated` offer | release profile only |
| `alternative_credit_offer` | integer `MCU` | opportunity/receiver | immutable funded offer from allocation; `simulated` | receiver-choice profile only |
| `origin_retention_credit_offer` | integer `MCU` | opportunity/origin | optional future funded comparator; `simulated` | receiver-choice profile only |
| `straight_line_distance` | `km` | origin/receiver pair | derived from observed coordinates; `reconstructed` | receiver-choice profile only |
| `receiver_availability_ratio` | ratio `[0,1]` | receiver/time | pre-allocation state; `reconstructed` or `simulated` according to trajectory | receiver-choice profile only |
| `receiver_scarcity_ratio` | ratio `[0,1]` | receiver/time | same frozen state used by eligibility; `reconstructed` or `simulated` | eligibility and audit guardrail; not an additional v1 utility term |

MCU is kept as an integer unit. Its scenario denomination (`1 MCU = EUR 0.01`
equivalent) is accounting metadata, not an observed exchange rate or proof of
real purchasing power. The response coefficients therefore retain `1/MCU`
rather than silently converting credits into an observed euro utility.

The current credit-allocation contract creates alternative-site offers, not
release credits or origin-retention credits. Those two signals are therefore
`not_applicable` in the initial implementation; they cannot be fabricated or
copied from an alternative offer.

## 4. Origin release profile

The v2 release form preserves the exponential mechanism:

\[
h^{release}_{i,1}(t)=h^{release}_{i,0}(t)
\exp\left[
\theta_{r,p}\,d^{price}_i(t-\tau_{r,p})+
\theta_{r,c}\,d^{release\_credit}_i(t-\tau_{r,c})
\right].
\]

| Parameter | Unit | Direction | Provenance |
| --- | --- | --- | --- |
| `theta_release_price` | `min/EUR` | non-negative | `assumed` |
| `theta_release_credit` | `1/MCU` | non-negative | `assumed` |
| `delay_release_price_minutes` | minutes | non-negative | `assumed` |
| `delay_release_credit_minutes` | minutes | non-negative | `assumed` |

A term whose signal is `not_applicable` is absent from the declared profile;
it is not fitted and is not reported as an active zero-credit experiment. An
applicable withheld term withholds the profile. A profile with every applicable
driver equal to zero reproduces the baseline exactly.

This channel remains a `charging -> available` proxy. It is not proof of charge
completion, post-charge idle or a person's reason for leaving.

## 5. Origin accepted-start profile

The initial v2 start profile retains the price-only response:

\[
h^{start}_{i,1}(t)=h^{start}_{i,0}(t)
\exp\left[-\theta_{a,p}\,d^{price}_i(t-\tau_{a,p})\right].
\]

`theta_start_price` has unit `min/EUR`, is non-negative and assumed. Its delay
is a separate non-negative assumed parameter. The negative sign is part of the
model contract: a positive origin contribution cannot increase the accepted
start hazard under this profile.

An alternative-site credit does not enter this equation. First the paired
simulator obtains the fixed-minus-policy difference in accepted-start proxies;
only those conserved redistribution candidates pass to receiver choice. This
ordering prevents the same credit from both suppressing an origin start and
selecting a destination.

As before, this is an `available -> charging` proxy, not total arrivals, rejected
demand, a queue or a claim that a real trip disappeared.

## 6. Receiver-choice profile

For a frozen choice opportunity `o`, let `J_o` be the alternatives that passed
eligibility and allocation. The initial systematic utility for receiver `j` is:

\[
V_{oj}=
\beta_c c_{oj}
-\beta_d d_{oj}
+\beta_a A_j,
\]

where `c` is MCU, `d` is kilometres and `A` is receiver availability.
Coefficient units are respectively `1/MCU`, `1/km`, and dimensionless for the
ratio input. All beta values are non-negative and assumed.

`receiver_scarcity_ratio = 1 - receiver_availability_ratio` when the same valid
capacity denominator is used. Including both in one utility would duplicate
one degree of freedom. Scarcity therefore remains an eligibility/reporting
guardrail in v1 rather than receiving a second coefficient.

The conserved outside/unassigned outcome has fixed reference utility
`V_outside = 0`. If a future origin-retention offer is approved, it receives a
separate utility with its own typed inputs; it must not reuse receiver distance
or availability. Choice probabilities use a stable softmax:

\[
P(j\mid o)=\frac{\exp(V_{oj})}
{\exp(V_{outside})+\sum_{k\in J_o}\exp(V_{ok})},
\qquad
P(outside\mid o)=\frac{1}
{1+\sum_{k\in J_o}\exp(V_{ok})}.
\]

Utilities are shifted by their maximum before exponentiation for numerical
safety. Probabilities must be finite, non-negative and sum to one within the
declared tolerance. The seeded paired simulator, not this deterministic
contract, draws the outcome.

This is a parameterized hypothetical choice mechanism, not an estimated modal
choice model. Straight-line distance is a friction proxy, not road travel time.

## 7. Timing and causal ordering

Each profile selects the latest available signal no later than its own
`evaluation_time - delay`. Signals are piecewise constant; no interpolation or
future lookup is allowed. Choice signals use the immutable offer and frozen
receiver state from the allocation batch and are not re-read after seeing a
random draw.

The execution order is:

```text
qualified baseline + policy/adoption
    -> origin price signal
    -> release and accepted-start probabilities
    -> paired transition draws
    -> conserved redistribution candidates
    -> eligibility + funded immutable offers
    -> deterministic choice probabilities
    -> paired choice draw
    -> atomic capacity/MCU reservation
```

Credits cannot affect a timestamp before their offer exists. Credit issuance
and later redemption cannot be used as response inputs for the choice that
caused them.

## 8. Identity, monotonicity and conservation invariants

1. All applicable intervention signals zero reproduces the corresponding
   baseline transition profile exactly.
2. Zero credit cannot create a credit-response effect.
3. Increasing price cannot reduce release hazard or increase origin-start
   hazard when all other inputs are held fixed.
4. Increasing an alternative offer cannot reduce that alternative's choice
   probability with the choice set fixed.
5. Increasing distance cannot increase that receiver's choice probability
   with other inputs fixed.
6. Increasing receiver availability cannot reduce that receiver's choice
   probability with other inputs fixed.
7. Choice probabilities, including outside, sum to one.
8. One opportunity yields exactly one choice outcome.
9. Redistribution candidates are conserved across receiver-selected,
   deferred/unresolved and unassigned outcomes.
10. No response result can override eligibility, pool fundability, offer expiry
    or atomic receiver-capacity checks.
11. Equipment/data-quality transitions remain outside every behavioural
    profile.

Monotonicity is a property of the declared functional form. It does not prove
that Vilnius users actually behave in that direction.

## 9. Required response outputs

Every deterministic evaluation records:

- bundle, scenario, replication and opportunity identities;
- profile/model identity and version;
- baseline model and trajectory identity;
- every signal value, unit, state, timestamp, provenance and source event;
- every assumed coefficient and delay with units;
- exponent or systematic-utility components separately;
- adjusted hazard/probability or the complete normalized choice vector;
- withheld/not-applicable reasons;
- claim scope `scenario_conditional`.

The stochastic event additionally records the random seed/substream and chosen
outcome. Repeated simulation changes uncertainty about scenario output; it does
not turn assumed beta/theta parameters into estimated behaviour.

## 10. Compatibility with implemented v1 channels

The current `effective_policy_adjustment` scalar is a valid compatibility
mapping to `origin_price_contribution_rate` only when its identity, unit and
policy/adoption lineage are preserved. Existing release/start implementations
remain v1 and operational while steps 8 and 9 add v2 typed profiles.

Compatibility does not permit:

- feeding MCU into the `EUR/min` scalar;
- summing price, credit and distance before the response boundary;
- using the allocation priority score as a choice probability;
- treating a missing credit signal as an offered zero credit;
- changing old results while retaining their v1 version label.

## 11. Validation and claim boundary

The contract rejects duplicate signal identities, unit or scope mismatch,
naive timestamps, future data, non-finite values, invalid bounds, inconsistent
choice sets, unsupported outputs and numerically unsafe exponents/utilities.

All coefficients and delays remain `assumed` until an intervention study and
declared estimator satisfy the Vilnius validation gate. Results are
`simulated`, `scenario_conditional` and may answer “under which assumptions?”;
they may not claim observed elasticity, causal effect, welfare improvement or
forecasted individual behaviour.

## 12. Step-seven acceptance decision

The approved generalized boundary uses typed signals with separate units,
coefficients, delays and scopes. Release and accepted-start remain exponential
hazard profiles; alternative selection is a separate normalized choice profile
with an explicit outside outcome. Policy construction, behavioural assumptions,
random draws, capacity reservation and accounting remain distinct layers.

Step 8 may now extend the executable release response to the v2 price plus
optional release-credit profile without changing the current alternative-site
credit allocation semantics.
