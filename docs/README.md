# Documentation map

This directory contains the technical contracts behind the MATEMAFIJA project
guide. Read the [full guide](../output/pdf/matemafija_project_guide.pdf) first
for the integrated architecture and presentation story; use the documents below
for implementation-level definitions.

## Evidence layer

- [Database v2](database_v2.md) — OCPI/DATEX storage, time semantics, identity,
  revisions, mappings and security.
- [Variable dictionary](variable_dictionary.md) — canonical definitions,
  units, aggregation and provenance classes.
- [Observable scarcity metrics](scarcity_metrics.md) — allowed evidence and
  the boundary between zero availability and an unobserved queue.
- [Derivative statistics](derivative_statistics.md) — qualification and
  uncertainty rules.
- [Baseline readiness](baseline_readiness.md) — gates for description,
  transition estimation, F1 replay and counterfactual simulation.

## Baseline and policy layer

- [Observed tariff replay](fixed_policy.md) — factual F1 baseline.
- [Transition model](transition_model.md) — empirical availability/charging
  hazards and sparse-cell fallback.
- [Trajectory generators](trajectory_generators.md) — observed replay and
  local-day block bootstrap.
- [OSA-v1 adaptive policy](adaptive_policy.md) — bounded observable-scarcity
  adjustment and policy parameters.
- [Policy integration](policy_integration.md) — F1, OSA-v1, adoption and
  response-driver composition.

## Simulation and evaluation layer

- [Credit-circulation contract](credit_circulation.md) — approved product
  thesis, research question, terminology, DAEI separation and claim boundaries
  for the next implementation milestone.
- [Credit participants and events](credit_events.md) — logical roles, immutable
  event envelope, contribution/choice/credit state machines and reconciliation.
- [Mobility-credit unit](credit_units.md) — MCU denomination, integer precision,
  rounding, scenario wallets, issuance, partial redemption and expiry.
- [Contribution pool](credit_pool.md) — contribution accrual, causal funding,
  pool buckets, solvency reserve, subsidy and reversal treatment.
- [Receiver eligibility](receiver_eligibility.md) — quality, equipment,
  capacity, spatial, tariff, access and compatibility boundaries.
- [Credit allocation](credit_allocation.md) — funded batch exposure, bounded
  offer amounts, receiver slots and deterministic pair prioritization.
- [Credit-sensitive receiver choice](receiver_choice.md) — typed funded
  alternatives, assumed utility components, outside probability and selection
  pending reservation.
- [Append-only simulation ledger](simulation_ledger.md) — event replay, MCU
  conservation, receiver capacity and atomic two-resource reservation.
- [Fairness and safety guards](fairness_safety.md) — pre-reservation hard gates,
  observable distributional proxies and explicit non-evaluable boundaries.
- [Paired credit simulation grid](credit_simulation_grid.md) — downstream
  credit-choice, safety, capacity and ledger scenarios with common random
  numbers.
- [Four-domain credit evaluation](credit_simulation_evaluation.md) — separate
  system, redistribution, user-proxy and accounting outputs with explicit
  non-evaluable boundaries.
- [Joint credit-policy robustness](credit_robustness.md) — conjunctive domain
  gates, Wilson-bound scenario success and observable-scope claim limits.
- [Common simulator contract](simulator_contract.md) — modes, inputs, events,
  outputs and claim scopes.
- [Generalized policy-independent response contract](response_contract.md) —
  typed price, credit and spatial signals; exponential transition profiles;
  normalized receiver choice and assumption boundaries.
- [Release response](release_response.md) and [accepted-start response](arrival_response.md)
  — implemented hypothetical response channels.
- [Simulation grid](simulation_grid.md) — paired common-random-number protocol.
- [Shared evaluation](simulation_evaluation.md) — identical scarcity metrics
  for fixed and adaptive arms.
- [Robustness](robustness.md) — Wilson-bound success region and minimum tested
  response threshold.
- [Spatial redistribution](spatial_redistribution.md) — downstream displaced-use
  allocation and conservation guardrails.

## Communication

- [Data and modelling assumptions](assumptions.md)
- [Pitch narrative and demo sequence](pitch_narrative.md)
- `matemafija_project_guide.tex` — editable source for the public PDF guide.

All documents must preserve the same claim discipline: assumptions are not
observations, simulations are not forecasts, and current effectiveness results
remain scenario-conditional until a Vilnius intervention validates the response.
