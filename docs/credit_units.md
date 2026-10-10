# Mobility-credit unit and lifecycle contract

Status: **approved design contract v0.1; implementation pending**.

This document completes step 3 of the credit-circulation implementation plan.
It fixes the scenario accounting unit, numeric representation, rounding,
issuance, redemption, expiry and reversal semantics. It does not define the
contribution-pool formula or credit-allocation amount; those are steps 4 and 6.

## 1. Canonical unit

The MVP accounting unit is the **MATEMAFIJA Mobility Credit Unit**, canonical
code `MCU`.

One MCU has a policy-defined scenario redemption reference of:

```text
1 MCU = EUR 0.01-equivalent of eligible charging service
```

This definition is intentionally narrow:

- it is a simulator denomination, not legal tender;
- it is not an observed price, payment, receivable or operator liability;
- it is not withdrawable as cash;
- it is not transferable between users or scenario wallets;
- it has no conversion rate to DAEI or another external unit;
- it does not authorize the project to use a real operator's tariff or billing
  account;
- `EUR-equivalent` describes the proposed redemption basis, not a promise of
  monetary payment.

The display label may be `credits`, but every machine-readable result must use
`MCU` and the unit-contract version.

## 2. Numeric representation

All ledger amounts are non-negative integers in MCU. Floating-point values are
forbidden in accounting records.

Intermediate policy calculations may use `Decimal`. Conversion to MCU occurs
exactly once at the accounting boundary:

```text
amount_mcu = round_half_up(amount_eur_equivalent * 100)
```

Rules:

1. Use decimal arithmetic from source strings; do not construct accounting
   decimals from binary floats.
2. Use `ROUND_HALF_UP` only at the final conversion boundary.
3. Do not round each intermediate factor separately.
4. An active result below `0.5` MCU rounds to zero and must be recorded as
   `below_minimum_unit`, not silently omitted.
5. Negative values, NaN, infinity and boolean-as-integer values are invalid.
6. All events retain both `amount_mcu` and `unit_contract_version`; when an EUR
   equivalent was the source, retain the exact pre-rounded decimal string and
   conversion rule.

The default unit-contract identity is:

```text
unit_contract_id      = matemafija_mobility_credit
unit_contract_version = 0.1.0
unit_code              = MCU
minor_unit_scale       = 100 per EUR-equivalent
rounding_mode          = ROUND_HALF_UP
```

Changing denomination, scale or rounding requires a new unit-contract version.
Events from different versions cannot be added without an explicit migration.

## 3. Accounting modes

The same unit supports two explicitly different modes.

### 3.1 `unit_accounting`

Used with the current public-data prototype. It produces MCU from a versioned
scenario rule without asserting that a real duration, session bill or payment
was observed. Outputs are suitable for internal budget and sensitivity tests.

### 3.2 `session_accounting`

Reserved for a future pilot with qualified Session/CDR quantities and an
applicable tariff contract. It may convert a duration- or energy-based monetary
amount into MCU at the accounting boundary.

The modes must never be mixed inside one scenario ledger. A result must disclose
its mode. `unit_accounting` values must not be presented as collected EUR.

## 4. Scenario wallets

Until a real identity contract exists, issued credits belong only to a
`scenario_wallet_id`.

A scenario wallet:

- is a deterministic identifier scoped to one scenario and replication;
- contains no personal or vehicle identifier;
- cannot be joined to OCPI to infer a user;
- cannot transfer MCU to another wallet;
- exists only to test issuance, partial redemption, expiry and reconciliation;
- must be labelled `simulated`.

The same synthetic wallet may participate in later simulated charging-service
events only when that linkage is generated explicitly by the scenario. It must
not be inferred from similar station, time or status records.

## 5. Offer and reservation semantics

A `credit_offer_created` event declares a maximum available MCU amount and an
offer-expiry time. It creates no wallet balance and no liability.

An offer may transition to exactly one of:

- declined;
- expired;
- withdrawn;
- reserved.

A `credit_reserved` event atomically reduces the currently offerable pool but
does not increase the scenario-wallet balance. Its amount must be a positive
integer, cannot exceed the offer, and cannot be reserved by another choice
opportunity.

The initial MVP uses **full reservation**: the reserved amount equals the offer
amount. Partial reservation is prohibited in v0.1 to keep capacity and credit
commitments auditable.

If the qualifying action fails, the complete reservation is released. A
released reservation cannot later be issued.

## 6. Issuance semantics

`credit_issued` is allowed only when:

1. the offer was reserved;
2. the required qualifying action completed;
3. receiver capacity was validly consumed when redistribution is the action;
4. the same reservation has not been released or issued before;
5. the pool remains solvent under the future pool contract.

Issuance converts the full reservation into an outstanding scenario-wallet
balance. Partial issuance is prohibited in v0.1. The issuance event records:

- `amount_mcu`;
- `scenario_wallet_id`;
- `issued_at_utc`;
- `expires_at_utc`;
- qualifying action event ID;
- reservation event ID;
- unit and policy contract versions.

Issuance is simulated user benefit available, not benefit already consumed.
Reported realized user benefit is based on redemption, not offer or issuance.

## 7. Expiry policy

The MVP expiry period is a policy-defined **30 elapsed days** after issuance:

```text
expires_at_utc = issued_at_utc + 30 * 24 hours
```

Elapsed UTC duration is used so daylight-saving changes cannot make the rule
ambiguous. Credit is valid strictly before `expires_at_utc`. At that timestamp
the remaining outstanding balance expires.

An offer has a separate, shorter validity window that will be defined with the
allocation rule in step 6. Offer expiry and issued-credit expiry are different
events.

The 30-day value is an MVP policy parameter for stress testing, not an observed
operator practice or empirically optimized duration. Sensitivity analysis may
vary it, but every run must record the selected value.

## 8. Redemption semantics

MCU may be redeemed only against an eligible simulated charging-service amount.
Cash withdrawal, peer-to-peer transfer and negative billing are prohibited.

Partial redemption is allowed. For an issuance with original amount `I`, total
redemption `R` and non-negative reversal amount `V`:

```text
0 <= R + V <= I
outstanding = I - R - V
```

`V` is zero unless a valid compensating reversal reduces the issuance; it may
never make the effective issuance or outstanding balance negative.

Each redemption event must be a positive integer MCU amount. The payable
charging-service amount is a hard upper bound: credit cannot create a negative
charge or cash remainder.

When several issuances exist, redemption uses deterministic
**earliest-expiry-first**, then `issued_at_utc`, then issuance event ID. This
prevents arbitrary selection from changing expiry outcomes.

Lifecycle reporting distinguishes:

- `credit_partially_redeemed`: positive outstanding balance remains;
- `credit_fully_redeemed`: outstanding balance reaches zero;
- `credit_expired`: remaining positive balance expires.

A fully redeemed or expired issuance cannot be redeemed again.

## 9. Reversal semantics

A reversal is a new compensating event. It never edits the original event.

### Before issuance

- invalid contribution or reservation is reversed/released in full;
- no scenario-wallet balance is created.

### After issuance but before redemption

- the outstanding issuance may be reversed in full;
- the pool treatment is determined by the step-4 pool contract.

### After partial or full redemption

The MVP must not create a negative user wallet or retroactively erase consumed
benefit. A post-redemption correction is recorded as `reconciliation_exception`
and requires an explicit subsidy/shortfall treatment. It cannot silently debit
another issuance or scenario wallet.

Every reversal records a reason, operator/system role, original event ID and
amount. Cumulative reversals cannot exceed the affected outstanding amount.

## 10. Balances and conservation

For one scenario wallet at time `t`:

```text
wallet_outstanding_mcu(t)
  = cumulative_effective_issuance
  - cumulative_redemption
  - cumulative_expiry
  - valid_unredeemed_reversal
```

The result must be a non-negative integer.

At scenario level, the ledger must report separately:

- offered MCU;
- reserved MCU;
- issued MCU;
- partially and fully redeemed MCU;
- expired MCU;
- reversed MCU;
- outstanding MCU;
- reconciliation exceptions.

Offers are exposure, reservations are commitments, issuances are simulated
liabilities, and redemptions are simulated realized user benefit. These totals
must never be combined into one generic `credits` value.

## 11. Privacy and legal boundary

The unit contract introduces no real account, payment instrument or personal
data processing. A production or pilot implementation requires separate review
of at least:

- operator and payer obligations;
- consumer disclosure and refund rules;
- tax and accounting treatment;
- payment/e-money implications;
- identity, consent, retention and fraud controls;
- accessibility and non-discrimination;
- unclaimed and expired value;
- cybersecurity and audit.

No statement in this document determines the legal classification of a future
credit mechanism.

## 12. Step-three acceptance decision

The approved MVP uses integer MCU, a scenario value reference of EUR 0.01 per
MCU, full reservation and issuance, partial redemption,
earliest-expiry-first consumption and a 30-elapsed-day expiry. All current
events remain simulated. Step 4 may now define when contribution amounts accrue
to the pool and how reserves, reversals and optional subsidy are balanced.
