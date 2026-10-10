# Jury-facing Policy Lab flow

Status: **implemented interface flow v2.0.0**.

`src/policy_dashboard.py` completes step 16 of the credit-circulation plan. It
is a read-only Streamlit explanation and decision interface. It does not alter
the database or execute payments. Before the formal evidence gates pass it may
display only an explicitly labelled illustrative response surface, never a
formal effectiveness result.

## 1. Six-step navigation

The interface follows one stable presentation path:

1. **Evidence** — current OCPI/DATEX coverage, station map, tariffs and history
   gate using the read-only SQLite database.
2. **Policy** — origin scarcity signal, shared MCU pool and funded receiver
   offer lifecycle.
3. **Response** — explicitly assumed release, accepted-start and
   credit/distance receiver-choice curves.
4. **Evaluation** — system, redistribution, user-proxy and accounting domains,
   shown separately.
5. **Robustness** — conjunctive gate logic, non-evaluable treatment and the
   Wilson-bound scenario rule.
6. **Decision** — defensible current claims, prohibited claims, city pilot and
   DAEI separation.

This order mirrors the computation and provenance graph. Policy does not appear
as observed evidence, and explanatory response curves do not appear as measured
effects.

## 2. Evidence locking

The evidence tab computes the current collection span directly from timezone-
aware observations. Seven days is only the global duration prerequisite;
individual sites still require coverage, transition-event and F1 readiness.

When the global gate is closed, the evaluation/robustness tabs may render an
illustrative release-response surface calculated solely from declared assumed
parameters. It carries claim scope `illustrative_mechanism_only` and a permanent
warning that current history is not data-qualified. It is not evidence, a
forecast or an input to the robustness decision. When the gate is open, the
interface still requires versioned per-site run artifacts before a formal
effectiveness heatmap may be published.

## 3. Explanatory controls

The response tab exposes:

- OSA adjustment cap;
- release and accepted-start sensitivities;
- credit and distance choice sensitivities;
- illustrative baseline transition probabilities;
- illustrative receiver distance.

The plots are deterministic mechanism curves. Labels state that they are
assumptions, not fitted Vilnius elasticities. Formal runs use qualified
transition estimates, funded offers and paired candidate draws.

## 4. Four-domain and joint views

Four domain cards prevent a single system metric from standing in for the
whole policy. The robustness tab provides an interactive gate explainer:

```text
all pass                 -> replication success
any fail                 -> replication failure
otherwise unavailable    -> not_evaluable
```

Even a successful replication still needs the scenario-level minimum sample,
missingness cap and Wilson lower-bound rule. The UI uses the exact language
`joint observable robustness` and never labels it pilot validation.

## 5. MCU and DAEI communication boundary

The Policy tab states that MCU is a simulated accounting unit, not money or
cashback already paid. The Decision tab presents DAEI as Lithuanian precedent
and a possible future integration path, not as the current unit or computation
layer. This keeps the mentor-inspired circulation concept without claiming a
legal or technical equivalence.

## 6. Step-sixteen acceptance decision

The Policy Lab now tells the complete credit-circulation story in the same
order as the implemented contracts and preserves readiness locks and claim
boundaries. The public README, guide-facing links and repository documentation
now follow this final interface narrative.
