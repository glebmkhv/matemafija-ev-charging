# Baseline readiness report

This report defines when the observed OCPI/DATEX history is sufficient for each
stage of the pricing-policy study. Readiness is not one boolean: factual replay,
statistical description, transition-model fitting and tariff replay require
different evidence.

The executable assessment is implemented in `src/baseline_readiness.py`. Its
rules are versioned as `1.0.0`.

## Readiness gates

| Gate | Required evidence | What it permits |
| --- | --- | --- |
| `descriptive_replay_ready` | At least two eligible capacity snapshots and positive offered capacity. | Replay and preliminary description of the observed window. |
| `historical_profile_ready` | At least 7 days of history, 7 Vilnius local calendar days and at least 80% eligible expected-snapshot coverage at the configured five-minute cadence. | Qualified historical scarcity summaries and uncertainty intervals. |
| `transition_model_ready` | Historical-profile gate, at least two observed states, 40 complete uncensored intervals, 20 `available -> charging` proxies and 20 `charging -> available` proxies. | Estimation of a baseline state-transition model. |
| `f1_tariff_ready` | Every current connector at the site has a current tariff assignment and at least one observed OCPI price-component type is resolvable. | Factual `F1 — observed_tariff_replay` for that site. |
| `assumption_driven_simulation_ready` | Both transition-model and F1-tariff gates pass. | Counterfactual runs using explicit hypothetical response parameters. |

The transition sample-size limits are transparent initial engineering
thresholds, not claims of statistical optimality. Any change must increment the
readiness version and be documented.

## Tiers

- `assumption_driven_simulation_ready`: transition baseline and factual F1 are
  both usable;
- `transition_ready_tariff_incomplete`: transition model can be estimated, but
  factual price replay is incomplete;
- `historical_profile_only`: qualified descriptive statistics are possible,
  but transition evidence is insufficient;
- `descriptive_only`: only preliminary replay of the current observed window is
  supported;
- `not_ready`: even descriptive replay lacks two eligible snapshots.

Each site record contains the measured denominators, all failed gate reasons and
non-blocking warnings. A downstream simulator must use the booleans; it must not
infer readiness from the tier label alone.

## Data-quality treatment

- A snapshot is eligible only under the rules in `docs/scarcity_metrics.md`.
- Collection gaps and left/right censoring are not converted into transitions.
- A site without sufficient history can still expose preliminary point values,
  but no confidence interval or predictive language is allowed.
- A tariff assignment without resolvable price components is not a usable F1
  price function.
- DATEX matching is corroborating evidence and a warning dimension, not a hard
  simulation gate. The OCPI state series remains source-native and is never
  silently filled from DATEX.
- Passing readiness does not validate a behavioural price response. Parameters
  such as release sensitivity and response delay remain explicitly assumed
  until intervention data exist.

## Audit of the current database

Read-only audit of `data/ev_charging.db` on 2026-10-08:

| Fact | Current value |
| --- | ---: |
| OCPI locations with complete-snapshot observations | 1,984 |
| Observation window | 2026-10-06 12:48:39 UTC — 2026-10-07 20:34:02 UTC |
| Global history span | 1.323 days |
| Sites ready for descriptive replay | 1,853 |
| Sites with at least 7 days of history | 0 |
| Mean eligible-snapshot share across sites | 85.57% |
| Current connectors | 5,843 |
| Connectors with a current tariff assignment | 5,821 |
| Sites passing the complete F1 tariff gate | 813 |
| Sites with full assignment but no resolvable price components | 1,164 |
| Sites with partial connector-tariff assignment | 7 |
| Sites with a current DATEX station match | 1,980 |

Consequently, the current database supports a substantial descriptive replay
and factual F1 replay for 813 sites, but **no site yet passes the seven-day
historical gate**. Therefore no site is currently declared ready for fitting the
baseline transition model or for assumption-driven counterfactual simulation.
This is a data-window limitation, not a negative result about adaptive pricing.

The collector should continue running. Once the seven-day threshold is crossed,
the assessment must be rerun because transition counts, interval censoring and
site-level coverage can still prevent individual sites from passing.

## Baseline transition estimator

The state-transition estimator in `src/transition_model.py` accepts only sites
with `transition_model_ready=true`, preserves supported hour/day and site
heterogeneity, and estimates the two observable transition channels:

- `available -> charging` (charging-start proxy);
- `charging -> available` (release proxy).

Operational/non-operational transitions remain a separate process. The
estimator must not label either proxy as arrival, queue, charge completion or
post-charge idle behaviour. Its full estimator contract is documented in
`docs/transition_model.md`.
