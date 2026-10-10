# Mobility-credit offer allocation contract

Status: **approved design contract v0.1; implementation pending**.

This document completes step 6 of the credit-circulation implementation plan.
It determines how prior funded MCU is converted into bounded offers over an
immutable eligible choice set. It does not determine whether a user accepts an
offer; behavioural sensitivities and destination-choice probabilities remain
separate assumption-driven layers.

## 1. Separation of responsibilities

The credit flow has three distinct decisions:

1. `receiver_eligibility`: may this origin-receiver pair participate?
2. `credit_allocation`: what offer can be funded and exposed?
3. `choice_response`: under declared assumptions, which outcome is selected?

Allocation is `policy_defined`. Response coefficients are `assumed`. A high
offer may remain unselected, and an eligible receiver may receive no offer when
capacity slots or funded MCU are unavailable.

## 2. Allocation batch

Offers are allocated in one immutable batch for each:

```text
(scenario_id, replication_id, evaluation_time_utc)
```

Batch inputs are frozen before allocation:

- prior `pool_offerable_mcu` from the contribution-pool contract;
- redistribution choice opportunities at the timestamp;
- their origin contribution quotes;
- eligible origin-receiver pairs and gate reports;
- receiver pre-allocation state;
- receiver coordinates and distance;
- policy and contract versions.

The batch must not use contributions, expiry, subsidy or receiver state that
occurs later at the same or a future timestamp.

## 3. MVP parameters

| Parameter | Initial value | Meaning |
| --- | ---: | --- |
| `distribution_fraction_eta` | `0.80` | Maximum fraction of offerable MCU exposed by one timestamp batch. |
| `minimum_offer_mcu` | `1` | Smallest numeric offer. |
| `maximum_offer_mcu` | `25` | Per-opportunity issuance cap. |
| `maximum_offers_per_choice` | `3` | Maximum alternative offers shown to one choice opportunity. |
| `receiver_capacity_fraction` | `0.50` | Fraction of projected available EVSEs usable as offer slots. |
| `distance_supplement_cap_mcu` | `5` | Maximum additional offer for distance friction. |
| `availability_bonus_cap_mcu` | `5` | Maximum additional offer for strong receiver availability. |
| `distance_decay_scale_meters` | `2,000` | Scale for ranking nearby alternatives. |
| `offer_validity_seconds` | `600` | Offer expires after two expected five-minute collection intervals. |

All values are policy-defined MVP parameters and require sensitivity analysis.
They are not learned preferences or contractual operator terms.

## 4. Batch budget

Let `A_t` be `pool_offerable_mcu` immediately before the batch. The maximum
exposure budget is:

\[
B_t^{offer}=\left\lfloor\eta A_t\right\rfloor,
\qquad \eta=0.80.
\]

The remaining offerable MCU stays unexposed to reduce batch concentration and
support later timestamps. This is additional to the 10% solvency reserve.

An offer is an exposure, not a reservation. Nevertheless, the batch must be
fully fundable under a worst-case simultaneous acceptance rule:

\[
\sum_o \max_{j\in\mathcal E_o} r_{oj}
\leq B_t^{offer},
\]

where `o` indexes choice opportunities and only one receiver can be selected by
one opportunity. Therefore alternative offers for the same opportunity consume
exposure equal to their maximum, not their sum.

Across different opportunities, exposures are additive. This guarantees that
all displayed offers can be reserved if every opportunity accepts one of its
alternatives.

## 5. Receiver offer slots

For receiver `j`:

\[
slots_j=
\left\lfloor
A_j^{pre}\,f_{receiver}
\right\rfloor,
\qquad f_{receiver}=0.50.
\]

Each origin opportunity receiving an offer to `j` consumes one offer slot in
the batch. Thus:

\[
offer\_opportunities_j \leq slots_j.
\]

A receiver may pass eligibility with one available EVSE but have zero offer
slots after the conservative fraction is applied. This is reported as
`receiver_capacity_reserved_for_existing_demand`, not as withheld eligibility.

Offer slots are exposure controls, not actual capacity reservations. The
selected alternative must still reserve receiver capacity atomically before a
simulated receiver start.

## 6. Raw offer amount

For eligible origin opportunity `o` and receiver `j`, define:

- `q_o`: positive origin contribution quote in MCU;
- `d_oj`: haversine distance;
- `D_max`: eligibility distance limit, initially 5,000 m;
- `A_j`: receiver pre-allocation availability ratio;
- `A_min`: minimum receiver availability, initially 0.50.

Distance supplement:

\[
m_{oj}^{distance}=
\operatorname{round\_half\_up}
\left(
5\,\frac{d_{oj}}{D_{max}}
\right).
\]

Availability bonus:

\[
m_j^{availability}=
\operatorname{round\_half\_up}
\left(
5\,\frac{A_j-A_{min}}{1-A_{min}}
\right).
\]

Both components are clipped to `[0, 5]`. The raw offer is:

\[
r_{oj}^{raw}=
\operatorname{clip}
\left(
q_o+m_{oj}^{distance}+m_j^{availability},
1,
25
\right)\ \text{MCU}.
\]

Interpretation:

- the origin quote retains the strength of the qualified scarcity signal;
- a longer admissible diversion may receive more compensation;
- a receiver with more availability may receive a larger policy offer;
- the hard cap prevents an alternative from consuming an arbitrary share of
  the pool.

The formula does not estimate willingness to travel. The later response model
may show that the offer is too weak to overcome distance friction.

The offer is also not a claim that the receiver produces a lower total charging
bill. OCPI F1 tariff components remain visible to the response and reporting
layers, but a comparable realised session total requires energy, duration and
session/CDR evidence that the current public observations do not consistently
provide. MCU therefore represents a scenario incentive, not a certified net
saving.

## 7. Pair priority

Offer edges are ranked by a policy priority score:

\[
priority_{oj}=
A_j\exp\left(-\frac{d_{oj}}{2{,}000}\right).
\]

The score favors available nearby receivers. It does not contain a behavioural
coefficient and is not a choice probability.

Global deterministic ordering is:

1. descending `priority_oj`;
2. ascending distance;
3. origin site ID;
4. choice-opportunity ID;
5. receiver site ID.

The exact score and tie-break values are retained in the allocation audit.

## 8. Allocation algorithm

For each batch:

1. validate pool, unit and eligibility contract versions;
2. compute `B_t_offer` and receiver offer slots;
3. build all eligible origin-receiver edges;
4. calculate raw MCU offers and priority scores;
5. process edges in global deterministic order;
6. reject an edge if its receiver has no remaining offer slot;
7. reject an edge if its choice opportunity already has three offers;
8. calculate the incremental exposure created by adding the edge:

   ```text
   max(0, edge_offer_mcu - current_choice_max_offer_mcu)
   ```

9. accept the edge only if cumulative exposure plus the increment does not
   exceed the batch budget;
10. freeze all accepted offers and report every rejected edge with a reason;
11. pass the immutable offers to the response layer;
12. after choice, reserve exactly the selected offer's MCU and release no value
   for unselected alternatives because they were exposure only.

The algorithm never scales all offers proportionally after publication. An
offer is either created with an integer amount or absent.

## 9. Empty, small and exhausted pool behaviour

- `pool_offerable_mcu = 0`: emit no numeric offers and reason
  `pool_not_funded`.
- Batch budget rounds to zero: emit `batch_budget_below_minimum_unit`.
- Remaining budget below a proposed first offer: do not create an underfunded
  offer; emit `batch_budget_exhausted`.
- An opportunity may receive fewer than three offers.
- An eligible receiver may receive no offer because its slots or batch budget
  are exhausted.
- No offer is represented as zero MCU.

Lack of an offer is not evidence that the receiver is unsuitable or that a
driver rejected it.

## 10. Offer validity and immutability

Every created offer records:

- `offer_id` and choice-opportunity ID;
- origin and receiver site IDs;
- integer `amount_mcu`;
- `created_at_utc`;
- `expires_at_utc = created_at_utc + 600 seconds`;
- origin quote and each offer component;
- priority score and ranking inputs;
- pool balance, reserve and batch exposure at creation;
- receiver state, slot and eligibility identities;
- policy/unit/pool/eligibility/allocation versions;
- provenance `simulated` and claim scope `scenario_conditional`.

The amount and expiry of a published offer are immutable. A later state change
may withdraw the offer before reservation through a new event, but cannot edit
the original event.

## 11. Relationship to response and reservation

Allocation produces alternatives and amounts; it does not choose one.

The response layer receives for each alternative:

- credit amount;
- contribution quote at the origin;
- distance;
- receiver availability/scarcity;
- unresolved warnings.

After response:

- declined/unselected offers create no pool movement;
- selected offer must pass expiry and current receiver-capacity checks;
- successful selection atomically reserves both MCU and receiver capacity;
- insufficient balance despite a valid allocation is a reconciliation error,
  because the batch was required to be worst-case fundable;
- failed capacity reservation emits `selection_failed`, withdraws the offer and
  records no issuance.

## 12. Fairness boundaries retained for later steps

This allocation rule is deliberately simple. It does not yet prove fairness.
Later safeguards must evaluate:

- whether distant users require disproportionate compensation;
- whether small sites systematically receive no offer slots;
- whether early deterministic ordering systematically favors some origins;
- whether low-income or accessibility-constrained users face higher net cost;
- whether expiry or low redemption creates misleading apparent solvency;
- whether cross-operator participation changes offer access.

These are evaluation requirements, not reasons to insert unobserved demographic
attributes into the current model.

## 13. Required allocation outputs

Each batch reports:

- pool offerable MCU and batch exposure budget;
- accepted and rejected edge counts;
- offered choice-opportunity count;
- choice opportunities with no offer;
- offers and maximum exposure per opportunity;
- slots available/used per receiver;
- rejection-reason distribution;
- distance, availability, raw amount and priority distributions;
- total exposure and unused batch budget;
- all parameter and contract versions.

Canonical rejection reasons include:

```text
pool_not_funded
batch_budget_below_minimum_unit
batch_budget_exhausted
receiver_offer_slots_exhausted
choice_offer_limit_reached
receiver_not_eligible
origin_quote_withheld
contract_version_mismatch
```

## 14. Step-six acceptance decision

The MVP uses a fully funded worst-case exposure budget, conservative receiver
offer slots, a 1--25 MCU bounded offer, explicit distance and availability
components, and deterministic global allocation. It does not embed behavioural
sensitivity in the policy rule. The generalized typed response contract and its
release/accepted-start profiles are now implemented. Step 10 may consume these
immutable funded alternatives in the credit-sensitive receiver-choice layer.
