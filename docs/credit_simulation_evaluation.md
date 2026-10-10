# Four-domain credit-circulation evaluation

Status: **implemented evaluation contract v1.0.0**.

`src/credit_simulation_evaluation.py` completes step 14 of the
credit-circulation plan. It evaluates every downstream paired run in four
separate domains. It deliberately does not yet collapse them into one success
flag inside this module; the joint `policy_robust` criterion is implemented by
the subsequent `src/credit_robustness.py` layer.

## 1. System domain

The system block links each downstream run back to its exact upstream scarcity
evaluation and reports:

- adaptive-minus-fixed zero-availability snapshot-share change;
- adaptive-minus-fixed mean availability change;
- adaptive-minus-fixed mean operational-scarcity change;
- additional release proxies;
- deferred-or-displaced accepted-start proxies.

The three scarcity changes remain available only when the shared upstream
eligibility mask supports them. Stateful episode metrics remain
`not_evaluable`, because the simulator still makes one-step conditional
projections rather than carrying a complete state trajectory forward.

## 2. Redistribution domain

The redistribution block reports:

- total downstream candidate count;
- candidates with and without any funded offer;
- safety-pass and safety-block offer counts;
- receiver selections and outside/unassigned outcomes;
- realized redistribution and outside shares;
- receiver capacity consumed;
- offers blocked specifically by the residual-capacity guard;
- the batch distributional-proxy status.

Every candidate must reconcile as exactly one receiver selection or one outside
outcome. Receiver capacity consumed must equal realized receiver selections.
These remain simulated proxies, not observed trips.

## 3. User-proxy domain

The currently defensible user-facing proxies are:

- mean proposed and selected MCU;
- mean proposed and selected straight-line distance;
- p95 proposed straight-line distance;
- unresolved warning count;
- selected-offer count.

The following remain explicitly `not_evaluable`:

- complete session cost;
- road travel time;
- individual welfare or social marginal benefit;
- demographic fairness.

This prevents a credit amount or Euclidean distance from being mislabeled as
user benefit. A future pilot needs Session/CDR quantities, route evidence and
appropriate user/access evidence before these fields may change status.

## 4. Accounting domain

The accounting block reports:

- funded, available, reserved, outstanding and settled MCU;
- reserve target and currently offerable MCU;
- proposed offer exposure;
- issued MCU and issuance count;
- redemption rate when issuance exists;
- reconciliation difference and solvency/reconciliation status.

Issued MCU must equal outstanding plus settled MCU in the current grid, and the
funding identity must reconcile exactly. Proposed exposure is reported even
when safety prevents reservation; it is not treated as a liability.

## 5. Identity and claim boundary

Each evaluation retains the downstream scenario, upstream scenario and
replication identity. The evaluator refuses a downstream candidate count that
does not equal the upstream deferred/displaced-start proxy count.

All outputs remain `simulated` and `scenario_conditional`. Four-domain
evaluation makes trade-offs visible, but it does not prove causal effect,
individual welfare, demographic fairness or legal/accounting readiness.

## 6. Step-fourteen acceptance decision

The project can now inspect origin-system effects, redistribution realization,
limited user-facing proxies and ledger health without substituting one domain
for another. The implemented
[`credit_robustness.md`](credit_robustness.md) contract combines these outputs
conjunctively, with `not_evaluable` treated distinctly from success.
