# Contribution-pool and solvency contract

Status: **approved contract v0.2; core pool buckets and reserve replay implemented**.

This document completes step 4 of the credit-circulation implementation plan.
It defines contribution calculation, accrual timing, pool buckets, reserves,
subsidy disclosure, reversals and solvency. It does not select receiver sites or
determine how a fundable amount is divided between offers; those are steps 5
and 6.

## 1. Central accounting rule

The incentive pool is funded only by completed, valid scenario inflows:

- accrued scarcity contributions;
- an explicitly declared opening balance;
- an explicitly declared external subsidy.

A prospective contribution quote is not funding. A credit offer to one choice
opportunity cannot use the contribution that would arise only if that same
opportunity later remained at the scarce origin.

This breaks a circular dependency:

```text
wrong: future origin contribution -> current alternative offer -> choice

correct: prior funded pool -> current offer -> choice
         completed origin service -> future pool inflow
```

## 2. Contribution eligibility and timing

Contribution evaluation requires:

1. qualified scarcity evidence;
2. active OSA-v1 decision;
3. active rollout and selected treatment coverage;
4. non-equipment-dominated scarcity;
5. a non-withheld effective adjustment;
6. a versioned contribution policy;
7. a simulated qualifying origin-service event.

Before choice, the system may calculate a `contribution_quote`. The quote is a
policy signal visible to the response model but creates no obligation and no
pool inflow.

After choice:

- `origin_retained` followed by a valid `simulated_origin_start` may create
  `contribution_assessed` and `contribution_accrued`;
- `alternative_selected`, `action_deferred` or `candidate_unassigned` without a
  completed origin start creates no contribution;
- withheld, inactive, waived or equipment-driven decisions create no inflow;
- the same origin-service event can accrue at most once.

`candidate_unassigned` is not automatically chargeable: unassigned means the
choice model did not allocate a receiver, not that an origin service occurred.

## 3. Contribution amount in `unit_accounting`

The current public-data MVP has no observed session duration. It therefore uses
a declared reference interval rather than pretending to price a real session.

Let:

- `d_i(t)` be the effective OSA adjustment in EUR/min;
- `q_ref` be the policy-defined reference interval, initially 5 minutes;
- `s_MCU = 100` MCU per EUR-equivalent.

The scenario contribution is:

\[
c_i^{MCU}(t)=
\operatorname{round\_half\_up}
\left(d_i(t)\,q_{ref}\,s_{MCU}\right).
\]

With the current OSA cap of EUR 0.05/min and `q_ref = 5`, the maximum raw
contribution per qualifying origin opportunity is 25 MCU before any additional
future cap. This is a scenario accounting rule, not an observed five-minute
charge.

If a positive pre-rounded result is below 0.5 MCU, the outcome is
`contribution_waived` with reason `below_minimum_unit`. It is not accrued as
zero and not treated as withheld.

## 4. Contribution amount in `session_accounting`

Future pilot mode may use:

\[
c_i^{MCU}=
\operatorname{round\_half\_up}
\left(d_i\,q_i^{eligible}\,s_{MCU}\right),
\]

where `q_i_eligible` is a qualified applicable duration from Session/CDR and
the tariff contract. The mode requires observed session quantities, tariff
applicability and billing evidence. Reconstructed scarcity duration must never
substitute for session duration.

One scenario ledger cannot mix `unit_accounting` and `session_accounting`.

## 5. Pool buckets

For every scenario and replication, the ledger maintains three mutually
exclusive live buckets and one cumulative settlement sink:

| Bucket | Meaning |
| --- | --- |
| `available_mcu` | Funded MCU not committed to an offer or issued liability. |
| `reserved_mcu` | MCU atomically committed to accepted offers but not issued. |
| `outstanding_mcu` | Issued MCU not yet redeemed, expired or validly reversed. |
| `settled_mcu` | Cumulative MCU redeemed against eligible simulated service. |

Offers do not enter a bucket. They are exposure limits only. Reservation moves
MCU from `available` to `reserved`; issuance moves it from `reserved` to
`outstanding`; redemption moves it from `outstanding` to `settled`.

Release, expiry and valid unredeemed reversal move MCU back to `available`:

- released reservation: `reserved -> available`;
- expired outstanding credit: `outstanding -> available`;
- reversed unredeemed issuance: `outstanding -> available`.

These are transfers, not new funding.

## 6. Funding identity

Define cumulative funded MCU:

\[
F_t = O + C_t + S_t - X_t,
\]

where:

- `O` is opening funded balance;
- `C_t` is cumulative effective accrued contribution;
- `S_t` is cumulative external subsidy;
- `X_t` is cumulative valid reversal of previously accrued funding.

The core conservation identity is:

\[
F_t = A_t + R_t + L_t + Z_t,
\]

where:

- `A_t` is available MCU;
- `R_t` is reserved MCU;
- `L_t` is outstanding issued MCU;
- `Z_t` is cumulative settled/redemption MCU.

Expiry, reservation release and unredeemed issuance reversal change the
distribution between live buckets but do not change `F_t`. Funding reversal
changes `F_t` and must preserve non-negative live buckets.

Every event application must leave the identity exact in integer MCU. A nonzero
reconciliation difference invalidates the run.

## 7. Opening balance and subsidy

The default values are:

```text
opening_balance_mcu = 0
external_subsidy_mcu = 0
```

With both values at zero, the mechanism has a genuine cold start: no credit can
be reserved until earlier origin-service contributions have accrued.

For demonstrations or policy experiments, a positive opening balance or
subsidy is allowed only when the run records:

- amount in MCU;
- funding role ID;
- activation timestamp;
- policy reason;
- whether the source is repayable;
- provenance `policy_defined` for the rule and `simulated` for the inflow;
- explicit disclosure in all user-facing results.

An unnamed `external_funding_role` may be used. It must not be labelled as
Vilnius Municipality, an operator, DAEI, Baltpool or another real institution
without evidence and authorization.

## 8. Solvency reserve

The MVP protects a fraction of currently unsettled funded value from new
reservations. The initial policy parameter is:

```text
solvency_reserve_ratio = 0.10
```

Let unsettled funded value be:

\[
U_t = F_t-Z_t=A_t+R_t+L_t.
\]

At time `t`:

\[
reserve\_target_t=
\left\lceil 0.10\,U_t\right\rceil,
\]

\[
offerable_t=
\max\left(0,A_t-reserve\_target_t\right).
\]

The reserve is not a fifth accounting bucket and is not spent. It is the
minimum part of `available_mcu` protected from new credit reservations. Existing
issued liabilities remain valid if later events raise the reserve target.

The 10% value is policy-defined and must be varied in sensitivity analysis. It
is not an empirically optimal reserve or a legal capital requirement.

## 9. Reservation and issuance constraints

Before reservation:

```text
requested_offer_mcu <= offerable_mcu
```

Reservation is atomic. Competing opportunities are processed in the stable
event order defined by the event contract. If the remaining offerable balance
is insufficient, the offer is withheld or capped according to the future
allocation contract; overdraft is forbidden.

Issuance converts an existing reservation and therefore creates no additional
funding requirement. It cannot exceed the reservation. Redemption cannot
exceed outstanding MCU or the eligible service amount.

## 10. Contribution reversals and shortfall

An assessed but not accrued contribution may be reversed without pool impact.

For an accrued contribution reversal:

1. reduce effective cumulative contribution funding;
2. use unprotected available MCU first;
3. then use the protected reserve if necessary;
4. never cancel or debit another scenario wallet silently;
5. never make any bucket negative.

If available MCU cannot cover the reversal because funds are reserved, issued
or settled, record:

```text
funding_shortfall_mcu > 0
reconciliation_exception = true
```

The run is not `policy_robust` unless an explicitly declared subsidy covers the
shortfall. A post-redemption correction is not recovered from the simulated
user.

## 11. Expiry and breakage

When issued MCU expires, the remaining amount moves from `outstanding_mcu` to
`available_mcu`. It may support later offers, subject to the reserve target.

The model reports expired MCU separately as `expired_mcu`; it must not present
expiry as new contribution revenue or user benefit. Sensitivity analysis must
expose whether apparent solvency depends materially on non-redemption.

## 12. Accounting modes and causal interpretation

Pool balance can influence whether a credit offer is fundable and therefore can
enter the future choice set. It does not alter the observed scarcity evidence or
OSA score.

The temporal direction is mandatory:

```text
past funded events -> current offerability -> current assumed response
current completed origin service -> future funded balance
```

The model must not use future contributions, future expiry or future subsidy to
retroactively fund a current offer.

## 13. Required pool outputs

Every evaluated timestamp reports:

- opening balance;
- accrued contributions;
- external subsidy;
- effective funding reversals;
- total funded MCU;
- available, reserved, outstanding and settled MCU;
- reserve target and offerable MCU;
- expired and released MCU;
- funding shortfall;
- reconciliation difference;
- accounting mode and all contract versions.

The output must distinguish `gross contribution assessed` from
`effective contribution accrued`.

## 14. Step-four acceptance decision

The approved pool is integer-MCU, temporally causal and fully funded. The
current default has zero opening balance, zero subsidy, a five-minute reference
interval in `unit_accounting`, and a 10% protected reserve. Contributions accrue
only after qualifying simulated origin service. Credit reservations can use
only prior available funded MCU. Step 5 may now define which receiver sites are
eligible to receive credit-backed redistribution offers.
