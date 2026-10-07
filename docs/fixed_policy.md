# Fixed policy: observed tariff replay

Status: **implemented v1.0**.

The only fixed baseline is `observed_tariff_replay`. It reconstructs the tariff
published for the selected connector and session. It contains no invented fee,
scarcity trigger, queue, grace period or behavioural response.

## Sources and authority

OCPI is the calculation source because it provides the connector-to-tariff
assignment and structured Tariff → TariffElement → PriceComponent hierarchy.
DATEX II is independent, site-level corroborating evidence. A matched DATEX
price is preserved in the output but is never added to the OCPI amount: both
feeds describe the same physical service and adding them would double count.

The provenance chain is:

```text
connector → historical connector tariff assignment → OCPI tariff key
  → source revision known at session start → ordered tariff elements
  → restrictions and price components

connector → OCPI location → canonical physical site → DATEX station
  → DATEX rate, validity periods, pricing policy and published text
```

## Required session input

Actual tariff calculation requires quantities that location/status feeds do not
contain. `ChargingSessionUsage` therefore requires observed Session/CDR/meter
periods with connector and session timestamps, energy in kWh, charging seconds,
connected non-charging seconds, average power when restricted, and reservation
state when restricted.

No quantity is inferred from an EVSE status. Without these observations the
result is `WITHHELD`; F1 remains a real tariff baseline, not a synthetic bill.

## OCPI applicability algorithm

For every homogeneous charging period and each dimension independently:

1. inspect tariff elements in source order;
2. choose the first element containing that dimension whose restrictions match;
3. apply at most one component of that dimension at that time;
4. allow different dimensions to come from different matching elements;
5. charge zero for a dimension when no element matches, as prescribed by OCPI.

Implemented restrictions are local clock time (including overnight ranges),
date, weekday, cumulative session energy, average power, cumulative duration
and reservation state. Input periods must be split at tariff boundaries.

## Units, steps and tax

| Component | Published unit | `step_size` unit |
|---|---:|---:|
| `ENERGY` | currency/kWh | Wh |
| `TIME` | currency/hour charging | second |
| `PARKING_TIME` | currency/hour not charging | second |
| `FLAT` | currency/session | not applicable |

Energy rounding is applied once per session and excess is priced by the last
active energy component. Time rounding is applied once across charging and
parking: if parking exists, only the last parking period receives rounding;
otherwise the last charging period does. A flat component is charged once per
matching tariff element.

`published_total` preserves the tariff's tax convention. If tax is included it
is already gross. If tax is excluded and VAT exists for every charged component,
`total_including_vat` is also returned. Ambiguous tax metadata is never treated
as zero VAT.

## DATEX evidence

For every canonical-site match the replay retains station/rate identifiers,
currency, pricing policy, overall start time, valid periods, all published text,
and conservatively parsed energy, flat and parking price signals. DATEX parsing
is evidence extraction, not billing logic. A contradiction is a data-quality
finding, not a reason to average or replace structured OCPI prices.
The output classifies the cross-check as no match, non-comparable currency,
no numeric signal, numeric overlap, or no numeric overlap; it does not promote
that check to a billing rule.

## Output and scope

`TariffReplayResult` contains status, exact tariff/revision IDs, currency and
tax semantics, component-level measured and billed quantities, source price,
step size, costs, all matched DATEX evidence and reason codes.

With current location/status collection F1 can provide the complete connector
tariff catalogue and DATEX cross-check. An actual bill requires observed
Session/CDR/meter quantities; until then it must not claim user bill, revenue,
released capacity, queue reduction or behavioural effect.

For fixed/adaptive comparison both policies receive the same observed session.
The adaptive change is reported separately from the factual F1 component bill
before any combined counterfactual amount is calculated.

Implementation: `src/fixed_policy.py`. Tests: `tests/test_fixed_policy.py`.
