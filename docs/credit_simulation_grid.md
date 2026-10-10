# Paired credit-circulation simulation grid

Status: **implemented downstream paired grid v1.0.0**.

`src/credit_simulation_grid.py` completes step 13 of the credit-circulation
plan. It extends every upstream price/release/accepted-start run through funded
receiver offers, credit-sensitive choice, safety decisions and append-only
ledger outcomes. It does not invent receiver eligibility or allocation: those
remain immutable inputs until their approved contracts receive executable
implementations.

## 1. Two-stage experiment

The experiment now has two composable Cartesian products:

```text
upstream:
lambda x theta_release x theta_arrival x response_delay x replication

downstream:
beta_credit x beta_distance x reserve_ratio
            x minimum_residual_receiver_capacity
```

The upstream run produces conserved `RedistributionCandidate` records. For
each downstream coordinate, candidates are copied under a new scenario wallet;
the observed/reconstructed trajectory and upstream results remain unchanged.

## 2. Input boundary

The downstream runner requires:

- a validated `SimulationGridResult`;
- zero or more immutable `FundedReceiverOffer` records per upstream candidate;
- receiver capacity per `(receiver_site_id, evaluation_time_utc)`;
- an opening scenario balance and declared safety specification.

An absent offer set remains an explicit outside/unassigned choice. Missing
receiver capacity is treated as zero by the simulation safety boundary and
blocks reservation; it is not presented as an observed fact.

Funded offers are supplied rather than synthesized because receiver eligibility
and global allocation are still approved design contracts. This preserves the
implementation sequence and prevents a hidden heuristic from becoming policy.

## 3. Paired random-number protocol

The upstream seed remains attached to every downstream run. The receiver-choice
stream uses:

```text
choice_seed = choice_random_seed + replication_index
```

The generator is reset to that seed for every downstream scenario and consumes
exactly one uniform draw per redistribution candidate, even when no offer
passes safety. Therefore scenarios with different credit sensitivity, distance
sensitivity, reserve or residual-capacity policy use the same candidate-level
innovations. Outcome differences follow from declared parameters, not unrelated
random noise.

## 4. Per-candidate execution order

For candidates ordered by UTC time and stable ID, the runner performs:

```text
open timestamped receiver capacity
        -> evaluate every proposed offer against current ledger state
        -> retain only safety-pass alternatives
        -> evaluate normalized receiver choice
        -> draw receiver or outside outcome
        -> atomically reserve receiver capacity and MCU
        -> simulate receiver start and issue MCU
        -> terminate every unselected live offer
```

Safety is recalculated from the current replayed ledger before choice. Earlier
choices can therefore exhaust a receiver timestamp account or reduce offerable
MCU for later candidates. A safety-passed selection that then fails atomic
reservation is treated as an internal reconciliation failure, not a normal
behavioural outcome.

## 5. Run outputs and invariants

Each run returns:

- complete upstream and downstream scenario coordinates;
- upstream and choice seeds;
- candidate and funded-offer counts;
- safety pass/block counts and decisions;
- one receiver/outside outcome per candidate;
- successful reservations and issuances;
- the distributional proxy audit;
- the final replayed ledger snapshot.

The validator requires:

- every proposed offer has exactly one safety decision;
- every candidate has exactly one terminal choice outcome;
- selected receivers, reservations and issuances reconcile exactly;
- MCU accounting has zero reconciliation difference;
- common random numbers remain enabled;
- the result covers the full upstream × downstream product.

## 6. Claim boundary

The extended grid is still an assumption-driven policy stress test. Credit and
distance coefficients are assumed; reserve and residual-capacity limits are
policy-defined; choices, capacity use and ledger events are simulated. A run
does not show that a real person moved, received value or benefited.

## 7. Step-thirteen acceptance decision

The project now has one reproducible paired path from observed-baseline
transition stress testing to credit-sensitive receiver choice, safety gating,
capacity reservation and MCU issuance. The executable boundary remains honest
about its current allocation inputs. The implemented step-14
[four-domain evaluator](credit_simulation_evaluation.md) now calculates system,
redistribution, user-proxy and accounting outputs from these reconciled runs.
Step 15 may define joint policy robustness.
