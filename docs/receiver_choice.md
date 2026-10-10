# Credit-sensitive receiver-choice model

Status: **implemented assumption-driven mechanism v1.0.0**.

`src/receiver_choice.py` completes step 10 of the credit-circulation plan. It
converts one validated redistribution candidate and its immutable funded offers
into normalized destination probabilities and one simulated choice outcome.

It does not allocate offers, reserve capacity or MCU, issue credit, identify a
person, or prove that a journey occurred.

## 1. Inputs and layer boundary

The model accepts:

- one unit-level `RedistributionCandidate` from paired simulation;
- zero to three `FundedReceiverOffer` records from the allocation layer;
- one versioned set of assumed choice coefficients;
- a separate random uniform for the final draw.

Each funded offer retains offer/candidate/origin/receiver identities, allocation
rank, integer MCU, straight-line distance, frozen receiver availability and
scarcity, validity interval, eligibility decision, allocation batch and
contract versions.

An offer is admitted only when:

- it belongs to the candidate and origin;
- receiver differs from origin;
- amount is an integer from 1 through 25 MCU;
- distance remains inside the 5 km eligibility gate;
- receiver availability is at least 0.50 and scarcity is its exact complement;
- timestamps are timezone-aware and the offer was created at the candidate's
  decision timestamp;
- offer, receiver and allocation-rank identities are unique;
- provenance matches the declared evidence/simulation boundary.

An empty funded choice set is valid and yields outside probability one.

## 2. Systematic utility

For candidate `o` and funded receiver `j`:

\[
V_{oj}=\beta_c c_{oj}-\beta_d d_{oj}+\beta_a A_j,
\]

where:

- `c_oj` is the immutable integer MCU offer;
- `d_oj` is haversine distance in kilometres;
- `A_j` is frozen pre-allocation receiver availability;
- `beta_credit_per_mcu`, `beta_distance_per_km` and `beta_availability` are
  non-negative `assumed` scenario parameters.

Every component and their reconciled total are reported separately. This is a
parameterized hypothetical response, not an estimated Vilnius utility model.

Availability already affects the policy offer and can create a second direct
choice pathway only if `receiver_availability_visible = true`. The MVP default
is `false` with `beta_availability = 0`. This prevents the model from silently
assuming that users see live availability and supports an explicit ablation of
the direct availability effect.

Scarcity is not a second utility term because, under the same denominator,
`scarcity = 1 - availability`. It remains an eligibility and reporting
guardrail.

## 3. Outside outcome and probabilities

Outside/unassigned is always present with reference utility zero:

\[
P(j\mid o)=\frac{e^{V_{oj}}}
{1+\sum_{k\in J_o}e^{V_{ok}}},
\qquad
P(outside\mid o)=\frac{1}
{1+\sum_{k\in J_o}e^{V_{ok}}}.
\]

The implementation subtracts the maximum utility before exponentiation. Every
probability must be finite and `[0,1]`; the complete vector, including outside,
must sum to one within numerical tolerance.

The deterministic evaluation preserves allocation rank. The stochastic draw
uses receiver alternatives in that rank order and assigns the remaining
probability interval to outside. A fixed random uniform therefore reproduces
the same result for the same evaluation.

## 4. Monotonicity and interpretation

With the choice set and other attributes fixed:

- increasing an offer cannot reduce its own probability;
- increasing distance cannot increase its own probability;
- when the visibility assumption is active, increasing availability cannot
  reduce its own probability;
- zero coefficients give equal probability to every receiver and outside.

These are properties of the chosen mathematical form, not observed behavioural
facts. The coefficients must be varied in sensitivity analysis until pilot
evidence supports estimation.

## 5. Selection is not reservation

A receiver draw produces:

```text
receiver_selected_pending_reservation
```

or:

```text
outside_unassigned
```

The selected result records offer, receiver and MCU amount, but explicitly sets
`reservation_required = true`. It creates no ledger movement and consumes no
receiver capacity. The implemented ledger atomically rechecks offer expiry,
capacity and pool balance before emitting reservation and later issuance
events.

Outside/unassigned contains no offer, receiver or MCU and requires no
reservation. It is not automatically interpreted as refusal, abandonment or
unserved real demand.

## 6. Outputs and provenance

Every evaluation records:

- candidate, scenario, replication and UTC identities;
- model and contract versions;
- all assumed beta values and the availability-visibility assumption;
- every alternative's raw attributes and utility components;
- receiver and outside probabilities and their reconciled sum;
- `simulated` provenance and `scenario_conditional` claim scope.

Every draw additionally records the random uniform and selected outcome. The
module uses no user identity or demographic attribute.

## 7. Step-ten acceptance decision

Credit, distance and optionally visible receiver availability now influence a
transparent, normalized choice mechanism with an explicit outside outcome.
Choice remains strictly downstream of origin response and funded allocation,
and strictly upstream of reservation, issuance and receiver-state mutation.

The append-only simulation ledger and atomic reservation boundary are now
implemented without changing the behavioural model. The step-12 fairness and
safety contract now gates reservation and audits observable distributional
proxies. The step-13 downstream grid now integrates choice, safety and ledger
outcomes using one paired draw per candidate. Step 14 may evaluate the results.
and safety guards.
