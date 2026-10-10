# Final repository acceptance audit

Status: **passed for public demonstration; not pilot-validated**.

Audit date: **10 October 2026**. This document closes step 18 of the approved
credit-circulation plan. It reconciles the implementation, formal contracts,
Policy Lab, public guide and repository hygiene. Passing this audit means that
the repository is internally consistent and demonstrable; it does not mean that
the policy effect has been causally validated in Vilnius.

## 1. Acceptance result

| Area | Result | Evidence |
| --- | --- | --- |
| Data provenance and time semantics | Pass | OCPI/DATEX source facts, reconstructed variables and assumptions remain separated; stored timestamps are timezone-aware UTC. |
| Baseline and policy separation | Pass | F1 replays observed component tariffs; OSA-v1 is a separate, bounded and versioned adjustment. |
| Response modelling | Pass | Release, accepted-start and receiver-choice effects are explicit assumed parameters, not reported as fitted elasticities. |
| Paired simulation | Pass | Fixed and adaptive arms preserve paired paths, eligibility and random draws. |
| MCU accounting | Pass | Offer, reservation, issuance, redemption and pool reconciliation remain distinct; unfunded issuance is prohibited. |
| Four-domain evaluation | Pass | System, redistribution, user-proxy and accounting outcomes are evaluated separately. |
| Joint robustness | Pass | Missing evidence is `not_evaluable`; success requires all gates plus replication, missingness and Wilson-bound thresholds. |
| Claim discipline | Pass | No observed queue, post-charge idle time, welfare, demographic fairness or causal effect is claimed. |
| Jury interface | Pass | The six-tab Policy Lab follows evidence → policy → response → evaluation → robustness → decision. |
| Public-repository hygiene | Pass with owner action | No tracked database, credentials or large data artifact; public/private audience wording, documentation languages and notebook validity were checked. A licence still requires an owner choice. |

## 2. Verification performed

The final state was checked with:

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -p 'test_*.py'
python src/collect.py --help
python -m streamlit run src/policy_dashboard.py --server.headless true
```

The automated suite contains **156 passing tests**. Local Markdown links,
tracked-file inventory, generated-artifact policy, diff whitespace and obvious
credential patterns were also checked. The exploratory notebook is valid,
output-free and path-portable. The public project guide was compiled and
visually inspected page by page during documentation acceptance.

## 3. Contract reconciliation

The canonical computation and communication sequence is:

```text
OCPI + DATEX evidence
  → reconstructed state and qualified scarcity
  → F1 observed tariff baseline
  → OSA-v1 contribution signal and funded MCU alternatives
  → declared price/credit/distance/delay response assumptions
  → paired trajectories and append-only accounting
  → system + redistribution + user-proxy + accounting evaluation
  → joint observable robustness
  → bounded pilot recommendation
```

The same sequence is used by the README, project guide, pitch narrative,
Policy Lab and technical contracts. MCU remains a simulated mobility-credit
accounting unit. It is not money, deployed cashback or DAEI; DAEI is only a
Lithuanian precedent and possible future integration path.

## 4. Remaining gates are intentional

The following do not block a public hackathon demonstration, but they block
stronger operational claims:

- collect enough qualified history and rerun per-site readiness gates;
- obtain Session/CDR evidence for charging completion and session behaviour;
- estimate behavioural response from a controlled pilot;
- agree operator funding, receiver eligibility, allocation and settlement;
- validate routing, accessibility, cross-operator acceptance and demographic
  distribution with appropriate data;
- complete legal, privacy and consumer-protection review;
- choose and add an open-source licence before inviting external reuse.

Therefore these values remain fixed in the current public-data model:

```text
full_user_welfare_validated = false
demographic_fairness_validated = false
pilot_ready = false
```

## 5. Final decision

MATEMAFIJA is accepted as a coherent, reproducible and claim-safe hackathon
prototype. It is ready to be shown as a policy stress-testing digital twin and
as a design for a measurable city pilot. It is not represented as a deployed
payment system, an empirically proven behavioural intervention or a substitute
for regulatory validation.
