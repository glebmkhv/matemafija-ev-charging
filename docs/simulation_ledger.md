# Append-only simulation ledger

Status: **implemented event-sourced ledger v1.0.0**.

`src/simulation_ledger.py` completes step 11 of the credit-circulation plan. It
records simulated MCU, choice and receiver-capacity lifecycles as immutable
events and reconstructs every balance by replay. It is not a payment account,
production settlement system, blockchain or evidence that money moved.

## 1. Event-sourced boundary

The ledger is isolated by:

```text
(scenario_id, replication_index)
```

Events are exposed as an immutable tuple. Existing events cannot be edited or
deleted; corrections require later compensating events. Every append is first
validated by replaying the complete prospective log. Only a fully valid batch
is then appended.

The common envelope records event and sequence identities, UTC time, scenario,
replication, correlation and causation, policy identity, trajectory, random
seed, execution mode, claim scope, provenance and unit/event versions.

Sequence numbers are contiguous, event IDs unique, time cannot move backwards,
and causation can reference only an earlier event in the same ledger.

## 2. Accounting state

The replayed MCU buckets are:

- `available_mcu`;
- `reserved_mcu`;
- `outstanding_mcu`;
- cumulative `settled_mcu`.

Funding is opening balance, explicit subsidy and accrued contributions, net of
valid funding reversal events. After every event:

\[
funded=available+reserved+outstanding+settled.
\]

All values are non-negative integer MCU. A non-zero reconciliation difference
rejects the prospective append.

The 10% default solvency reserve remains a derived floor rather than a fifth
bucket:

```text
reserve_target = ceil(reserve_ratio * (available + reserved + outstanding))
offerable = max(0, available - reserve_target)
```

Offers do not move MCU. Reservation moves `available -> reserved`; issuance
moves `reserved -> outstanding`; redemption moves `outstanding -> settled`;
release or unredeemed expiry/reversal returns the applicable amount to
`available`.

## 3. Receiver-capacity accounts

Receiver capacity is opened per `(receiver_site_id, evaluation_time_utc)` and
replayed in three states:

- available;
- reserved;
- consumed by simulated receiver start.

One selected alternative consumes exactly one available capacity unit on
reservation. Release restores it; simulated receiver start moves it from
reserved to consumed. Negative or overbooked capacity is impossible.

These are simulated per-timestamp capacity accounts, not physical charger
locks.

## 4. Atomic selection and reservation

`record_choice` first validates the selected outcome and registered immutable
offer, then checks:

- the offer is still live and unexpired;
- remaining offerable MCU covers its complete amount;
- one receiver-capacity unit remains at the decision timestamp.

On success, one append batch records, in order:

```text
alternative_selected
receiver_capacity_reserved
credit_reserved
```

The prospective batch is replayed before mutation. Therefore capacity and MCU
cannot be partially reserved.

On insufficient pool or capacity, the batch records selection plus
`selection_failed`, without moving either resource. A missing/unregistered
offer is treated as a reconciliation error rather than an ordinary behavioural
failure.

## 5. Issuance and later lifecycle

A successful reservation may follow either path.

Completion:

```text
simulated_receiver_start
credit_issued
```

These two events are appended atomically. Credit cannot be issued before the
qualifying simulated receiver start.

Failure before completion:

```text
receiver_capacity_released
credit_reservation_released
selection_failed
```

The full MCU and capacity commitments are restored.

Issued MCU supports partial and full redemption. Expiry or reversal consumes
only the remaining unredeemed issuance and returns it to available MCU. Prior
redemption remains in settled MCU and is never silently reclaimed.

Unselected offers may terminate as declined, expired or withdrawn. Each state
is distinct and requires an explicit reason.

## 6. Candidate and lifecycle reconciliation

Replay maintains independent state machines for:

- candidates;
- offers;
- reservations;
- issuances;
- receiver capacity;
- MCU buckets.

A candidate may have only one choice path. A selected offer cannot be selected
again, an issuance cannot precede action completion, redemption cannot exceed
remaining issuance, and a released reservation cannot later be issued.

Passing replay proves internal scenario consistency only. It does not validate
legal liability, operator participation, user identity, billing integration or
real service delivery.

## 7. Step-eleven acceptance decision

The simulation now has an append-only event log, exact integer-MCU replay,
candidate and credit lifecycle state machines, capacity accounting and an
atomic two-resource reservation boundary. Selection remains distinguishable
from reservation, receiver start, issuance and redemption.

The implemented [fairness and safety contract](fairness_safety.md) evaluates
each funded alternative against the current replayed snapshot before
reservation. The [step-13 downstream grid](credit_simulation_grid.md) now
integrates that gate with paired choice and ledger replay without weakening
accounting conservation. Step 14 may evaluate the reconciled outcomes.
