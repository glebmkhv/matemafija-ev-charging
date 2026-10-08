# Hack4Vilnius pitch narrative

## Positioning

**Matemafija is a policy stress-testing digital twin for Vilnius EV charging
infrastructure.** It does not sell an unvalidated fee formula as a prediction.
It shows when an adaptive policy would work, how strong user response would
need to be, and which access or spatial trade-offs could offset the benefit.

## Three-minute story

### 1. The city problem — 25 seconds

EV charging capacity can be unavailable even while the city lacks direct queue,
waiting-time and post-charge-idle observations. A new price has never been
deployed, so its behavioural effect cannot honestly be learned from current
Vilnius history.

### 2. What we built from real data — 35 seconds

We continuously organize OCPI and DATEX observations, preserve source-native
timestamps and relationships, reconstruct EVSE state intervals, calculate
observable scarcity, and replay the actual component-based OCPI tariff as F1.
The database already contains a large descriptive baseline, but the formal
seven-day transition gate must still be satisfied before publishing scenario
effectiveness results.

### 3. The adaptive policy — 30 seconds

OSA-v1 adds a bounded, transparent TIME adjustment only when qualified,
sustained observable scarcity exists. It never uses an invented physical queue
or unobserved post-charge idle time. `lambda` controls price intensity; rollout
and coverage remain separate variables.

### 4. The digital twin — 50 seconds

Instead of claiming to know user elasticity, we vary explicit response
assumptions:

- how price changes `charging -> available` release probability;
- how price changes the accepted `available -> charging` start proxy;
- how delayed that response is;
- how much of displaced use may move to nearby stations.

Fixed and adaptive arms share the same baseline path and random numbers and are
evaluated with exactly the same scarcity definitions.

### 5. The decision output — 25 seconds

The output is not one optimistic forecast. It is a robustness map over
`lambda × theta_release × theta_arrival × delay`. A cell is robust only when
the lower 95% Wilson bound for improvement probability is at least 80%. The
model identifies the minimum tested response threshold and simultaneously
reports displaced accepted starts and scarcity transferred to receiving sites.

### 6. The ask — 15 seconds

Continue collection, select a small group of qualified pilot sites, deploy a
bounded OSA-v1 test, measure sessions and displaced use, and replace assumptions
with Vilnius evidence. The city receives a falsifiable pilot design rather than
a promise.

## Recommended demo sequence

1. Open the Evidence tab and show the live station map, tariff structure and
   readiness gate.
2. Open Mechanism and move `lambda`, `theta_release` and `theta_arrival` to
   demonstrate identity at zero and opposite response directions.
3. Open Robustness and explain why the effectiveness heatmap remains locked
   until data gates pass.
4. Explain the future heatmap, minimum tested threshold and displaced-demand
   guardrail.
5. Finish on Decision narrative and the bounded pilot proposal.

## Claim discipline

Say:

> Under explicitly declared response assumptions, the model identifies the
> parameter region where adaptive pricing robustly improves observable scarcity.

Do not say:

> We proved that the fee will eliminate queues or that Vilnius drivers have the
> assumed elasticity.

## Jury-facing strengths

- grounded in real municipal OCPI/DATEX data and actual tariffs;
- mathematically explicit and reproducible;
- useful under limited behavioural data;
- honest about uncertainty and causal limits;
- converts uncertainty into a measurable pilot threshold;
- exposes access and network spillover instead of optimizing a single metric.

