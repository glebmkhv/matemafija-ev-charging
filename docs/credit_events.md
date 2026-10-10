# Credit-circulation participants and event contract

Status: **approved design contract v0.3; implementation pending**.

This document completes step 2 of the credit-circulation implementation plan.
It defines logical participants, event identities, lifecycle transitions and
ordering. It deliberately does not fix the credit denomination, pool formula,
receiver-eligibility thresholds or allocation weights; those belong to steps
3--6.

## 1. Scope and modelling unit

The current simulator has no observed person or user account. Its behavioural
unit is an anonymous `choice_opportunity`: a simulated opportunity associated
with an accepted-start proxy that may remain at an origin, be deferred, become
unassigned or be allocated to an eligible receiver.

A `choice_opportunity` is not a driver, trip, rejected arrival or contractual
customer. It must not contain a name, vehicle registration number, payment
credential or any other invented personal identifier.

The event contract is valid only in
`assumption_driven_counterfactual` until an external identity, billing and
validation contract is approved. `observed_replay` may evaluate the existing
tariff and OSA mechanism but cannot emit contribution, credit or behavioural
choice transactions.

## 2. Logical participants

| Participant | Responsibility in the model | What it is not |
| --- | --- | --- |
| `policy_authority` | Owns the versioned contribution, credit, reserve, eligibility and safeguard rules. In the MVP this is a configuration role. | It is not automatically Vilnius Municipality, a regulator or a legal counterparty. |
| `scenario_ledger` | Records immutable simulated contribution and credit events and derives balances by scenario and replication. | It is not a bank account, payment service or production ledger. |
| `origin_site` | Qualified scarce OCPI location at which OSA and contribution eligibility are evaluated. | It is not proven to contain a queue or rejected driver. |
| `receiver_site` | Alternative OCPI location that passes the future receiver-eligibility contract and exposes capacity to the choice layer. | It is not guaranteed to be compatible or selected by a real user. |
| `choice_opportunity` | Anonymous simulated unit presented with an origin outcome and, when available, a set of alternative offers. | It is not an observed person, vehicle, session or arrival. |
| `charging_operator_role` | Future settlement and service-delivery role needed for a real pilot. It may own one or more sites. | Operator identity, consent and liability are not inferred from public feeds. |
| `user_account_role` | Future pseudonymous recipient required for actual issuance and redemption. | It does not exist in the present public-data model. |
| `external_funding_role` | Optional declared source of subsidy beyond contribution inflow. | It is not assumed to be the city, DAEI, Baltpool or any named organization. |

Participants are roles, not legal findings. A future pilot must map each role to
a real entity through a separate governance and data-protection agreement.

## 3. Common event envelope

Every credit-circulation event must contain:

- `event_id`: globally unique immutable identifier;
- `event_type` and `event_version`;
- timezone-aware `event_time_utc`;
- `scenario_id` and `replication_id`;
- `correlation_id`: groups the complete origin-to-outcome flow;
- `causation_event_id`: direct parent event, except for allowed roots;
- `policy_id` and `policy_version` where a rule is applied;
- `execution_mode` and `claim_scope`;
- `provenance`;
- involved role IDs, using source-native site IDs where applicable;
- `reason_code` for every withheld, declined, released, expired, reversed,
  deferred, unresolved or unassigned outcome;
- source trajectory identity and random seed when simulation randomness is used;
- payload schema version.

Accounting events use non-negative integer `MCU` amounts under
[`credit_units.md`](credit_units.md). Offer, reservation, issuance, redemption,
expiry and reversal events must include `amount_mcu` and
`unit_contract_version`. Evidence and non-accounting choice events do not invent
amounts.

### Identity and replay rules

1. `event_id` is unique across the complete result.
2. Reprocessing the same deterministic input must produce the same semantic
   event set; storage retries must not create duplicate economic effects.
3. `correlation_id` is stable from the originating policy evaluation through
   the terminal choice and accounting outcomes.
4. `causation_event_id` must reference an earlier event in the same scenario and
   replication.
5. Reversal creates a new event linked to the event being reversed. It never
   mutates or deletes history.
6. Fixed and adaptive arms may share source evidence but cannot share mutable
   ledger balances or transaction IDs.

## 4. Evidence and policy-decision events

These events establish why an intervention is or is not allowed. They do not
yet transfer value.

| Event type | Provenance | Required parent | Meaning |
| --- | --- | --- | --- |
| `scarcity_evidence_qualified` | `reconstructed` | observed snapshot/policy evaluation context | Site state passes the current scarcity evidence and quality rules. |
| `scarcity_evidence_withheld` | `reconstructed` | observed snapshot/policy evaluation context | Evidence is insufficient or disallowed; a reason code is mandatory. |
| `osa_decision_active` | `policy_defined` | qualified scarcity evidence | OSA produces an active raw/effective adjustment. |
| `osa_decision_inactive` | `policy_defined` | qualified context | OSA is evaluated but its activation rule is false. |
| `osa_decision_withheld` | `policy_defined` | qualified or withheld context | No numeric OSA value may be consumed downstream. |
| `contribution_evaluated` | `policy_defined` | active OSA decision | Contribution rule and non-binding quote are evaluated for the origin opportunity. |
| `contribution_withheld` | `policy_defined` | contribution evaluation | No contribution may accrue; reason code is mandatory. |
| `contribution_waived` | `policy_defined` | contribution evaluation | A valid rule explicitly produces no contribution, for example a future exemption. This is distinct from withheld. |
| `contribution_assessed` | `simulated` | contribution evaluation plus completed simulated origin service | A positive scenario obligation is created under a valid rule. It is not an observed payment. |

`contribution_assessed` is not the same as cash collection or pool availability.
The accounting lifecycle below determines whether and when an assessed amount
becomes available.

The pre-choice quote is not assessed or accrued. Contribution timing, amount
and funding buckets are defined in [`credit_pool.md`](credit_pool.md).

## 5. Contribution lifecycle

The allowed contribution states are:

```text
evaluated
  |-- withheld        (terminal)
  |-- waived          (terminal)
  `-- assessed
        |-- accrued
        |     `-- reversed
        `-- reversed
```

Events:

| Event type | Meaning |
| --- | --- |
| `contribution_accrued` | The assessed scenario amount enters the incentive pool under the future accounting-mode rules. |
| `contribution_reversed` | A compensating event removes a previously assessed or accrued obligation because a declared validation or settlement condition failed. |

An assessed contribution may be reversed before accrual. An accrued
contribution may be reversed only if the future pool contract defines how
already reserved or issued credits remain solvent. A reversal can occur at most
once per effective contribution state.

Forbidden transitions include:

- withheld or waived to assessed/accrued;
- inactive or withheld OSA to assessed;
- contribution from equipment-dominated scarcity;
- accrued without assessed;
- deletion or in-place editing of an assessed/accrued event;
- labelling assessed/accrued as an observed user payment.

## 6. Receiver and offer events

| Event type | Provenance | Meaning |
| --- | --- | --- |
| `receiver_evaluated` | `policy_defined` over reconstructed/simulated state | Receiver candidate is checked under the versioned eligibility contract. |
| `receiver_eligible` | `policy_defined` | Candidate passes all currently defined gates. |
| `receiver_ineligible` | `policy_defined` | Candidate fails a gate; reason code is mandatory. |
| `receiver_withheld` | `policy_defined` | Available evidence cannot determine eligibility. |
| `choice_set_created` | `simulated` | Immutable set of eligible receiver offers visible to one choice opportunity at one decision time. |
| `credit_offer_created` | `simulated` | Conditional offer associated with exactly one choice opportunity and receiver. |
| `credit_offer_withheld` | `simulated` | No numeric offer can be created because policy, evidence or pool information is withheld. |

An eligible receiver does not guarantee an offer: the future allocation rule
may produce no fundable offer. An offer does not reserve capacity or credit
until the corresponding reservation events exist.

## 7. Choice and capacity events

Every redistribution candidate must reach exactly one terminal choice outcome:

```text
redistribution_candidate_created
  |-- origin_retained
  |-- action_deferred
  |-- candidate_unassigned
  `-- alternative_selected
        |-- receiver_capacity_reserved
        |     |-- simulated_receiver_start
        |     `-- receiver_capacity_released
        `-- selection_failed
```

| Event type | Provenance | Meaning |
| --- | --- | --- |
| `redistribution_candidate_created` | `simulated` | An accepted-start difference enters the spatial-choice layer. |
| `response_assumption_applied` | `assumed` | Records the exact price, credit, distance and state sensitivities/delays used. |
| `origin_retained` | `simulated` | Candidate does not move away from the origin under the scenario response. |
| `simulated_origin_start` | `simulated` | A projected accepted-start proxy completes at the origin and may qualify for contribution assessment. |
| `alternative_selected` | `simulated` | Choice model selects one offered receiver; this is not a real trip. |
| `action_deferred` | `simulated` | Candidate is delayed beyond the current decision step under an explicit model. |
| `candidate_unassigned` | `simulated` | No terminal allocation is made; reason distinguishes no offer, nonparticipation and network-capacity exhaustion. |
| `receiver_capacity_reserved` | `simulated` | One unit of receiver capacity is atomically committed across competing origins. |
| `receiver_capacity_released` | `simulated` | A reservation is cancelled before a receiver start. |
| `simulated_receiver_start` | `simulated` | Reserved capacity is consumed by a projected accepted-start proxy. |
| `selection_failed` | `simulated` | A selected alternative cannot complete; reason and released reservations are mandatory. |

`alternative_selected` must never directly change receiver state. Capacity must
be reserved first. This preserves global capacity bounds when several origins
compete for one receiver.

## 8. Credit lifecycle

The allowed credit states are:

```text
offer_created
  |-- declined        (terminal)
  |-- expired         (terminal)
  |-- withdrawn       (terminal)
  `-- reserved
        |-- reservation_released
        `-- issued
              |-- partially_redeemed --> fully_redeemed
              |-- fully_redeemed
              |-- expired
              `-- reversed
```

Events:

| Event type | Provenance | Meaning |
| --- | --- | --- |
| `credit_offer_declined` | `simulated` | Choice outcome does not accept the offer. |
| `credit_offer_expired` | `simulated` | Offer expires before reservation. |
| `credit_offer_withdrawn` | `simulated` | Policy or eligibility change removes an unreserved offer. |
| `credit_reserved` | `simulated` | Pool amount is atomically committed to the selected offer. |
| `credit_reservation_released` | `simulated` | Reservation returns to the available pool before issuance. |
| `credit_issued` | `simulated` | Qualifying simulated action completes and creates credit liability. |
| `credit_partially_redeemed` | `simulated` | Positive MCU amount is applied and a positive issuance balance remains. |
| `credit_fully_redeemed` | `simulated` | Applied MCU amount reduces the issuance balance to zero. |
| `credit_expired` | `simulated` | Unredeemed issued credit expires under the future lifecycle rule. |
| `credit_reversed` | `simulated` | Compensating correction to an invalid issuance or redemption; original events remain. |

Issuance requires both a credit reservation and a successfully completed
qualifying action. In the initial redistribution case that means a
`simulated_receiver_start` linked to the same choice opportunity. A mere
`alternative_selected` event is insufficient.

Forbidden transitions include:

- offer directly to issued or redeemed;
- reservation without a fundable offer;
- issuance without reservation and qualifying action;
- redemption before issuance;
- redemption after expiry or full prior redemption;
- simultaneous terminal outcomes for one lifecycle;
- cumulative redemptions exceeding effective issuance;
- treating an offer or reservation as user benefit already received.

## 9. Deterministic event ordering

Within one UTC decision timestamp, future implementation must use this order:

1. ingest and validate the observed snapshot;
2. reconstruct site state and evaluate data quality;
3. qualify or withhold scarcity evidence;
4. evaluate rollout, coverage and OSA;
5. evaluate contribution eligibility and produce a non-binding quote;
6. construct receiver candidates and evaluate eligibility;
7. calculate offers using only prior funded pool balance and create an immutable
   choice set;
8. record the multidimensional response assumption;
9. draw origin/start and alternative-choice outcomes with the paired random
    design;
10. for retained origin service, emit `simulated_origin_start`, then assess and
    accrue its contribution for future timestamps;
11. for a selected alternative, atomically reserve receiver capacity and credit;
12. emit the projected receiver start or release failed reservations;
13. issue credit only after the qualifying alternative action;
14. apply later redemption, expiry or reversal events when their conditions are
    reached;
15. reconcile candidate conservation, receiver capacity and ledger balances;
16. calculate evaluation outputs.

Stable IDs break ties. Pool and receiver reservations must be serialized within
one scenario/replication so that parallel origins cannot spend or allocate the
same resource twice.

## 10. Required terminal reconciliation

For every `correlation_id`, the result must establish:

- exactly one contribution outcome: withheld, waived, outstanding assessed,
  accrued or reversed;
- exactly one candidate choice outcome when a redistribution candidate exists;
- exactly one terminal state for every created offer;
- exactly one terminal state or explicitly outstanding balance for every
  reservation and issuance;
- no negative receiver capacity;
- no negative pool balance unless a separately declared subsidy facility is
  active;
- no orphan causation references;
- no event that changes observed/reconstructed source data.

The reconciliation output remains simulated and scenario-conditional. Passing
it proves internal accounting consistency, not legal settlement correctness.

## 11. Step-two acceptance decision

This contract completes step 2 when all subsequent modules use these role and
event names or introduce a versioned amendment. Step 3 has now fixed amounts,
units and lifecycle timing in [`credit_units.md`](credit_units.md). Python event
classes remain deferred until the receiver and allocation contracts determine
the remaining required fields. Contribution accrual, pool reserves, reversals
and optional subsidy are now defined in [`credit_pool.md`](credit_pool.md). The
receiver evaluation states, gates and reason codes are defined in
[`receiver_eligibility.md`](receiver_eligibility.md). The next action is to
generalize the response contract using the offer amounts and immutable choice
sets defined in [`credit_allocation.md`](credit_allocation.md).
