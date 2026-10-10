# Fairness and safety guards

Status: **implemented observable guard contract v1.0.0**.

`src/fairness_safety.py` completes step 12 of the credit-circulation plan. It
adds a pre-reservation safety decision for every funded receiver offer and a
batch-level distributional proxy audit. The module does not claim demographic
fairness, accessibility, route suitability or individual benefit: the public
OCPI/DATEX evidence does not contain the required user attributes.

## 1. Two distinct checks

The individual `OfferSafetyDecision` is a hard gate. A reservation is allowed
only when its status is `pass`. The batch `DistributionalProxyAudit` describes
how offers and outcomes are distributed across observable candidates and
receiver sites. Its possible states are `pass`, `block` and `not_evaluable`.

`not_evaluable` is intentionally different from `pass`: a small batch or
missing evidence cannot support a fairness conclusion.

## 2. Pre-reservation hard guards

The current policy-defined specification checks that:

- the offer has not expired;
- its integer MCU amount does not exceed the per-offer cap;
- the ledger's offerable balance can fund the complete amount;
- straight-line distance remains within the declared spatial gate;
- receiver availability remains above the declared minimum;
- one capacity unit exists and at least one unit remains after reservation;
- the ledger reconciles before any reservation is attempted.

The residual-capacity rule is crucial: redistribution must not improve an
origin by immediately creating zero availability at the receiver. These checks
are evaluated against one immutable offer, one redistribution candidate and
one replayed ledger snapshot immediately before atomic reservation.

## 3. Explicit unresolved warnings

Every offer carries limitations that cannot be verified with the current
evidence, including vehicle/connector compatibility, road travel time,
individual accessibility needs, cross-operator acceptance and total session
cost. Safety evaluation also records that demographic fairness is not
evaluable and that the result is not a personalized route recommendation.

A warning is not silently converted into a favourable assumption. A future
pilot may promote a warning to a hard guard only after the necessary evidence
and rule are versioned.

## 4. Distributional proxy audit

For a sufficiently large scenario batch the audit reports:

- share of candidates receiving no funded offer;
- maximum share of offers assigned to one receiver site;
- mean offer amount;
- mean and p95 straight-line distance;
- outside/unassigned outcome share;
- safety-block share;
- counts of unresolved warnings.

The default audit blocks a sufficiently large batch when more than 50% of
candidates receive no offer, one receiver receives more than 60% of offers, or
any evaluated offer fails a hard safety gate. Every offer must also have a
corresponding safety decision; incomplete guard coverage blocks the audit.
Fewer than 20 candidates yields `not_evaluable`. These thresholds are
policy-defined prototype values, not empirical estimates. The downstream grid
now varies the residual-capacity guard and preserves the complete specification
on every run; broader threshold sensitivity belongs in later experiment
configurations rather than being presented as a city standard.

## 5. Claim boundary

A passing proxy audit means only that the declared observable exposure and
safety thresholds passed in a simulated scenario. It does **not** establish:

- equal treatment of demographic or protected groups;
- accessible travel for a particular person;
- acceptable road travel time or total trip cost;
- legal non-discrimination compliance;
- real user welfare improvement.

All decisions retain `simulated` provenance and `scenario_conditional` claim
scope. The current MVP never produces a personalized recommendation.

## 6. Step-twelve acceptance decision

The project now has enforceable, typed pre-reservation guards and an honest
three-state distributional audit. Missing user evidence remains visible rather
than being synthesized. The step-13 downstream grid now integrates these
decisions with paired choice draws and ledger replay. The step-14 evaluator now
reports their system, redistribution, user-proxy and accounting consequences.
The step-15 joint criterion now treats a failed or non-evaluable safety domain
as distinct from success.
