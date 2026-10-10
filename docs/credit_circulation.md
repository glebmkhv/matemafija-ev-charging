# MATEMAFIJA credit-circulation contract

Status: **approved product and research contract v0.17; implemented core with
explicit eligibility/allocation and real-settlement boundaries**.

This document fixes the first step of the credit-circulation development plan.
It defines what the proposed mechanism means, which claims it permits, and
which concepts remain assumptions or future pilot requirements. It does not
assert that credits, cashback or settlement are already implemented.

## 1. Product thesis

MATEMAFIJA is evolving from a one-sided adaptive scarcity adjustment into a
balanced incentive mechanism:

```text
qualified scarcity at an origin site
        -> bounded scarcity contribution
        -> shared incentive pool
        -> mobility-credit offer at an eligible alternative
        -> assumed user response
        -> simulated release, deferral or spatial redistribution
        -> system, user, receiver-site and accounting evaluation
```

The short product claim is:

> MATEMAFIJA converts observable charging scarcity into balanced incentives: a
> bounded contribution at scarce stations can fund mobility credits for users
> who choose qualified less-scarce alternatives.

The project does not treat a higher price as the final product. The pricing
signal, credit offer and destination choice form one policy mechanism whose
effects are stress-tested before a city pilot.

## 2. Research question

The primary research question is:

> Under which explicitly declared price, credit, delay and spatial-choice
> response assumptions does a budget-constrained contribution-to-credit policy
> improve observable charging-capacity scarcity without merely suppressing
> accepted use, transferring scarcity to receiver sites, or imposing excessive
> generalized cost on users?

This extends, rather than replaces, the existing question about the minimum
behavioural response required for adaptive pricing to work. The response model
remains assumption-driven until intervention evidence exists.

## 3. Relationship to the existing system

The following implemented components remain authoritative:

- OCPI and DATEX remain separate observed evidence sources;
- EVSE is the capacity unit;
- state intervals, coverage rules and scarcity metrics remain unchanged;
- F1 remains the observed-tariff baseline;
- OSA-v1 remains the policy-defined scarcity signal;
- fixed and adaptive arms retain paired baseline paths and common random
  numbers;
- the same scarcity definitions evaluate both arms;
- queue length, waiting time and post-charge idle remain unavailable.

OSA-v1 answers **when and how strongly a scarcity intervention is eligible**.
The credit-circulation layer answers **how the resulting economic signal may be
reallocated and how users may respond**. Credits must not alter the evidence
used to decide whether scarcity exists.

## 4. Canonical terms

| Term | Definition | Initial provenance |
| --- | --- | --- |
| `scarcity contribution` | A bounded policy-defined charge or accounting-unit inflow associated with a qualified scarce origin. It is not a fine and is not an observed payment. | `policy_defined`; monetary realization is `unavailable` without billing evidence |
| `incentive pool` | Scenario ledger balance available to support eligible credit offers after reserves and prior obligations. | `simulated` |
| `mobility credit` | A proposed charging-service reward for an eligible action, normally selection of a qualified alternative site. It is not DAEI, legal tender or an existing operator balance. | rule is `policy_defined`; offer/issuance/redemption is `simulated` |
| `credit offer` | A conditional amount displayed or assigned before the assumed action occurs. | `simulated` |
| `credit reservation` | An amount temporarily committed to an action but not yet issued. | `simulated` |
| `credit issuance` | A simulated ledger event created after the scenario's qualifying action. It is not proof that a real person received value. | `simulated` |
| `credit redemption` | A simulated application of previously issued credit under versioned policy rules. | `simulated` |
| `origin site` | The qualified scarce site at which the intervention signal is evaluated. | identity/state are `observed` or `reconstructed`; role is `policy_defined` |
| `receiver site` | A candidate alternative that passes data-quality, equipment, capacity and spatial eligibility gates. | state is `reconstructed`; eligibility is `policy_defined`/derived |
| `redistribution candidate` | A fixed-minus-adaptive accepted-start proxy made available to the downstream choice layer. It is not an observed rejected driver. | `simulated` |
| `generalized user cost` | A scenario quantity combining contribution, credit, distance/time friction and other declared choice attributes. | formula is `policy_defined`; sensitivities and result are `assumed`/`simulated` |
| `policy robustness` | Joint success under scarcity, receiver, access/fairness and ledger constraints. It is stricter than scarcity improvement alone. | `simulated`, `scenario_conditional` |

The words `cashback`, `reward` and `credit` may be used in product explanation
only with the disclosure that the current layer is a policy proposal and
simulation. `Cashback` is not the canonical technical term until a real payer,
billing interface and redemption obligation exist.

## 5. Provenance boundary

The mechanism must preserve this chain:

```text
observed/reconstructed scarcity evidence
        -> policy-defined OSA and credit rules
        -> policy-defined multidimensional incentive driver
        -> assumed behavioural sensitivities and delays
        -> simulated state, choice and ledger events
        -> scenario-conditional evaluation
```

In particular:

1. A policy-selected contribution or credit is not `observed`.
2. A sensitivity to price, credit or distance is not `estimated` unless a
   documented estimator passes its evidence gate.
3. A simulated redistribution is not a real driver trip.
4. An offered credit is not an issued or redeemed credit.
5. A withheld value is unknown and must never be converted to zero.

## 6. Generalized response concept

The existing exponential response concept is retained. The scalar price driver
will be extended into a versioned vector of policy and spatial signals:

\[
\mathbf d_i(t)=\left(
d_i^{price}(t),
d_i^{release\_credit}(t),
d_i^{alternative\_credit}(t),
distance_{ij},
availability_j(t),
scarcity_j(t)
\right).
\]

The release channel may later take the form

\[
h^{release}_{i,1}(t)=h^{release}_{i,0}(t)
\exp\left(
\theta_{r,p}d_i^{price}(t-\tau_p)
+\theta_{r,c}d_i^{release\_credit}(t-\tau_c)
\right).
\]

The origin accepted-start channel retains the negative price-response direction:

\[
h^{start}_{i,1}(t)=h^{start}_{i,0}(t)
\exp\left(-\theta_{a,p}d_i^{price}(t)\right).
\]

The destination choice layer will use credit, distance and receiver state in a
separate normalized utility. Policy outputs and response assumptions must not
be collapsed into one unidentified coefficient. Exact formulas, units and
normalization are deliberately reserved for steps 6--10 of the implementation
plan.

## 7. Permitted claims

Before a controlled pilot, the project may state that:

- the system identifies qualified observable scarcity without claiming a
  physical queue;
- OSA-v1 produces a bounded policy signal under versioned rules;
- the proposed mechanism can redirect simulated contribution units toward
  qualified alternative-site credit offers;
- explicit assumed sensitivities connect price and credit signals to simulated
  release, accepted-start and destination-choice outcomes;
- the simulator can identify parameter regions in which scarcity improves while
  declared access, receiver-site and accounting safeguards pass;
- the result can define measurable thresholds for a city pilot.

Every such result must be labelled `scenario_conditional` and disclose the
policy version, response assumptions, trajectory identity and random seed.

## 8. Prohibited claims

Before appropriate Session/CDR, billing, identity and intervention evidence,
the project must not state that:

- a real user paid a scarcity contribution or received cashback;
- OCPI identifies the individual who released or changed a station;
- the system observed a rejected arrival, physical queue or waiting time;
- credits caused a real driver to relocate;
- reduced origin scarcity proves increased social welfare;
- an offered, issued or redeemed credit is the same event;
- the proposed credits are money, a regulated financial instrument or DAEI;
- one MATEMAFIJA credit has any conversion rate to DAEI;
- Baltpool or another external platform has accepted or implemented the policy;
- the city or an operator is already liable to fund redemption.

## 9. DAEI separation rule

DAEI is an external regulated renewable-transport-energy accounting mechanism.
MATEMAFIJA mobility credits are a proposed charging-balancing mechanism. Their
unit bases, eligible actions, participants, verification and legal purposes are
different.

DAEI is therefore outside the computation graph of this first development
milestone. A later evidence review may evaluate several possibilities without
preselecting one: conceptual precedent, operator-level data integration,
settlement infrastructure, funding source or closer compatibility. No bridge
may be implemented until its legal basis, metering evidence, participants,
transfer and retirement rules, interface and double-counting controls are
documented.

## 10. Non-negotiable design invariants

Future implementation must satisfy all of the following:

1. `lambda = 0` reproduces the fixed/baseline response.
2. Zero credit cannot create a credit-response effect.
3. Equipment-driven scarcity cannot fund a demand-management contribution.
4. No eligible alternative means no claim of beneficial redistribution.
5. Displaced proxies are conserved across redistributed, deferred, unresolved
   and unassigned outcomes.
6. Receiver capacity cannot be overbooked across competing origins.
7. Credit issuance cannot exceed the available scenario pool plus an explicitly
   declared subsidy.
8. Every offer, reservation, issuance, redemption, expiry and reversal remains
   distinguishable.
9. Scarcity improvement alone is not sufficient for `policy_robust` status.
10. The original observed and reconstructed records are never modified by
    counterfactual events.

## 11. Fixed implementation sequence

The approved sequence for the first PLAN milestone is:

1. product thesis and claim boundaries -- **complete in this contract**;
2. participants and event catalogue -- **complete in
   [`credit_events.md`](credit_events.md)**;
3. accounting unit and lifecycle rules -- **complete in
   [`credit_units.md`](credit_units.md)**;
4. contribution-pool formula and accounting modes -- **complete in
   [`credit_pool.md`](credit_pool.md)**;
5. alternative-site eligibility -- **complete in
   [`receiver_eligibility.md`](receiver_eligibility.md)**;
6. credit-allocation rule -- **complete in
   [`credit_allocation.md`](credit_allocation.md)**;
7. generalized policy-independent response contract -- **complete in
   [`response_contract.md`](response_contract.md)**;
8. release-response extension -- **implemented in
   [`release_response.md`](release_response.md)**;
9. accepted-start extension and redistribution candidates -- **implemented in
   [`arrival_response.md`](arrival_response.md)**;
10. credit-sensitive spatial choice -- **implemented in
    [`receiver_choice.md`](receiver_choice.md)**;
11. append-only simulation ledger -- **implemented in
    [`simulation_ledger.md`](simulation_ledger.md)**;
12. fairness and safety guards -- **implemented in
    [`fairness_safety.md`](fairness_safety.md)**;
13. paired simulation grid extension -- **implemented in
    [`credit_simulation_grid.md`](credit_simulation_grid.md)**;
14. system, redistribution, user-proxy and accounting evaluation --
    **implemented in
    [`credit_simulation_evaluation.md`](credit_simulation_evaluation.md)**;
15. joint policy-robustness criterion -- **implemented in
    [`credit_robustness.md`](credit_robustness.md)**;
16. Policy Lab flow -- **implemented in [`policy_lab.md`](policy_lab.md)**;
17. README and public documentation alignment -- **complete**;
18. tests, reconciliation and final acceptance audit.

Future work may refine a formula but must not weaken the claim boundary or
provenance separation without an explicit versioned amendment to this contract.

## 12. Acceptance state

Steps 1--17 are complete. The read-only Policy Lab follows the complete
evidence → policy → assumed response → paired simulation → four-domain
evaluation → decision path, retains readiness locks and explicitly separates
MCU from DAEI. README, pitch narrative, guide source and public documentation
now use the same architecture and claim language. The next action is the final
tests, reconciliation and acceptance audit.
