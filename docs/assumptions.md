# Data and modelling assumptions

## Observed public data

Values obtained directly from the public OCPI or DATEX II endpoints.

## Derived historical information

Estimates calculated from repeated public-data snapshots.

Timezone-naive OCPI timestamps from Via Lietuva are interpreted as
`Europe/Vilnius` local time. The unmodified source string is retained, and the
quality label records that the timezone was assumed.

## Simulation and model information

Queue length, exact post-grace idle time, SII, adaptive contribution, mobility
credit and cashback are not values supplied by OCPI or DATEX II. A contribution
or credit rule has `policy_defined` provenance; an offer, issuance, redemption,
ledger balance or behavioural outcome produced by the current research model
has `simulated` provenance.

Queue length and exact post-charge idle time are not currently observable in
the public feeds. They may only enter later work as explicitly documented and
validated estimates, or the policy model must be reformulated using observable
capacity-scarcity variables.

The approved product direction is a balanced contribution-to-credit mechanism,
not a one-sided penalty. OSA-v1 remains the observable-scarcity signal. Future
response models may combine price, credit, delay and spatial-choice signals, but
their sensitivities remain explicitly `assumed` until intervention evidence is
available. The normative boundary is defined in
[`credit_circulation.md`](credit_circulation.md).

Current public data do not identify an individual driver, prove a relocation,
or support real billing, credit issuance or redemption. Session/CDR, identity,
billing and pilot evidence are required before simulated accounting can be
described as a real user cashback mechanism.

DAEI and MATEMAFIJA mobility credits are separate concepts. DAEI does not enter
the current computation graph, and no conversion, funding or platform
integration is assumed before a dedicated legal, data and technical review.
