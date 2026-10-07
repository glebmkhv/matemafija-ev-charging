# Data and modelling assumptions

## Observed public data

Values obtained directly from the public OCPI or DATEX II endpoints.

## Derived historical information

Estimates calculated from repeated public-data snapshots.

Timezone-naive OCPI timestamps from Via Lietuva are interpreted as
`Europe/Vilnius` local time. The unmodified source string is retained, and the
quality label records that the timezone was assumed.

## Simulation and model information

Queue length, exact post-grace idle time, SII, adaptive fee and cashback
are model variables and must not be presented as values supplied by OCPI
or DATEX II.

Queue length and exact post-charge idle time are not currently observable in
the public feeds. They may only enter later work as explicitly documented and
validated estimates, or the policy model must be reformulated using observable
capacity-scarcity variables.
