# Joint observable-scope policy robustness

Status: **implemented joint criterion v1.0.0**.

`src/credit_robustness.py` completes step 15 of the credit-circulation plan. It
defines robustness as a conjunction of independently evaluated domains. A
strong origin-scarcity result cannot compensate for failed redistribution,
excessive user-distance proxy or broken accounting.

## 1. Per-replication gates

Every replication receives four gates:

1. **System** — the selected canonical scarcity metric must be available and
   improve by more than the declared minimum effect.
2. **Redistribution** — realized redistribution and outside shares must remain
   within their thresholds; the distributional proxy audit must pass and the
   residual-capacity guard must have no block when those requirements are
   enabled.
3. **Observable user proxy** — at least one selected offer must provide an
   evaluable straight-line distance, whose mean remains below the declared
   maximum.
4. **Accounting** — the ledger must be solvent and exactly reconciled.

The run status is determined without averaging:

```text
any failed gate       -> failure
no failure, any gap   -> not_evaluable
all four gates pass   -> success
```

Thus `not_evaluable` is never converted into success.

## 2. System metric direction

The criterion supports the existing canonical choices:

- `zero_availability_snapshot_share`: negative change is favourable;
- `mean_operational_scarcity_ratio`: negative change is favourable;
- `mean_availability_ratio`: positive change is favourable.

Changes are adaptive minus fixed. The minimum effect size and primary metric
are policy-defined experiment settings, not estimated optima.

## 3. Scenario-level robustness

Replications are grouped by the complete upstream-plus-downstream scenario ID.
For each scenario the evaluator reports:

- total, valid and `not_evaluable` replication counts;
- `not_evaluable` share;
- successful and failed valid counts;
- joint success probability;
- Wilson confidence interval;
- mean primary system change among valid runs.

The initial criterion requires:

```text
valid replications >= 20
not_evaluable share <= 0.20
Wilson lower bound of joint success probability >= 0.80
```

All thresholds are versioned policy choices and must be visible in results.
The Wilson lower bound prevents a small number of favourable stochastic draws
from being labelled robust.

## 4. Meaning of `observable_policy_robust`

`observable_policy_robust = true` means only:

> Within this declared scenario, assumed response model, current observable
> proxy set and confidence rule, all implemented domain gates passed robustly.

It does not mean that full user welfare, demographic fairness or real-world
causal effect has been validated. Every scenario summary therefore keeps:

```text
full_user_welfare_validated = false
demographic_fairness_validated = false
pilot_ready = false
```

These fields cannot become true in the current public-data model.

## 5. Step-fifteen acceptance decision

The project now has a conservative joint robustness region that preserves
domain failures and missing evidence rather than hiding them in a composite
score. Step 16 may expose this structure in the Policy Lab: controls, paired
trajectories, domain cards, scenario map and explicit validation boundaries.
