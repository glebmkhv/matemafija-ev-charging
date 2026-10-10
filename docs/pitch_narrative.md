# Hack4Vilnius pitch narrative

## Positioning

**Matemafija is a policy stress-testing digital twin for Vilnius EV charging
infrastructure.** It does not sell an unvalidated fee formula as a prediction.
It shows when a balanced contribution-to-credit policy could work, how strong
price and credit responses would need to be, and which access, spatial or
accounting trade-offs could offset the benefit.

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

### 3. The balanced policy — 35 seconds

OSA-v1 adds a bounded, transparent TIME adjustment only when qualified,
sustained observable scarcity exists. It never uses an invented physical queue
or unobserved post-charge idle time. Prior simulated contributions can fund MCU
offers at qualified less-scarce alternatives. Offer, reservation, issuance and
redemption are separate; MCU is not money, deployed cashback or DAEI.

### 4. The digital twin — 50 seconds

Instead of claiming to know user elasticity, we vary explicit response
assumptions:

- how price changes `charging -> available` release probability;
- how price changes the accepted `available -> charging` start proxy;
- how delayed that response is;
- how credit and straight-line distance affect receiver choice;
- how receiver capacity, pool reserve and safety gates constrain circulation.

Fixed and adaptive arms share the same baseline path and random numbers and are
evaluated with exactly the same scarcity definitions.

### 5. The decision output — 25 seconds

The output is not one optimistic forecast or one composite score. Every run
reports system, redistribution, user-proxy and accounting domains. A scenario
is `observable_policy_robust` only when all gates pass together, at least 20
valid replications exist, no more than 20% are non-evaluable, and the lower 95%
Wilson bound for joint success is at least 80%.

### 6. The ask — 15 seconds

Continue collection, agree operator/funding roles, select qualified pilot
sites, test bounded contribution and credit rules, measure sessions, choices,
redemption and displaced use, and replace assumptions with Vilnius evidence.
The city receives a falsifiable pilot design rather than a promise.

## Recommended demo sequence

1. Open the Evidence tab and show the live station map, tariff structure and
   readiness gate.
2. Open Policy and explain origin signal → MCU pool → funded alternative.
3. Open Response and move price, credit and distance sensitivities while naming
   them as assumptions.
4. Open Evaluation and show why four domains remain separate.
5. Open Robustness and show the labelled illustrative response surface. State
   once that the formal effectiveness result remains locked until data gates
   pass.
6. Finish on Decision, the bounded pilot proposal and DAEI separation.

## Claim discipline

Say:

> Under explicitly declared response assumptions, the model identifies the
> parameter region where a contribution-to-credit policy is jointly robust
> within observable system, redistribution, user-proxy and accounting limits.

Do not say:

> We proved that the fee will eliminate queues or that Vilnius drivers have the
> assumed elasticity.

## Jury-facing strengths

- grounded in real municipal OCPI/DATEX data and actual tariffs;
- mathematically explicit and reproducible;
- useful under limited behavioural data;
- honest about uncertainty and causal limits;
- converts uncertainty into a measurable pilot threshold;
- exposes access, network and accounting trade-offs instead of optimizing a
  single metric;
- connects scarcity intervention to balanced MCU circulation while keeping
  DAEI as a clearly separated future pathway.

