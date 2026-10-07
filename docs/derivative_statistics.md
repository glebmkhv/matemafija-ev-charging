# First derivative statistics

The first statistical layer estimates repeatable site-level properties from
observable OCPI capacity snapshots and zero-availability episodes. It does not
estimate queues, waiting time, post-charge idle or behavioural response.

The implementation is in `src/derivative_statistics.py`.

## Qualification requirements

Default requirements for publishing uncertainty intervals are:

- history span of at least 7 days;
- observations on at least 7 local calendar days in `Europe/Vilnius`;
- eligible snapshots covering at least 80% of snapshots expected at the
  configured collection cadence;
- at least 20 complete, uncensored episodes for an episode-duration percentile.

These are initial engineering thresholds. They are deliberately stricter than
the requirements for testing the reconstruction code and may be revised only
through a documented change.

If a site fails any general threshold:

- descriptive point estimates are still returned;
- `statistically_qualified` is false;
- `qualification_reasons` records every failed criterion;
- confidence intervals are `None` and must not be invented downstream.

## Point estimates

For eligible snapshots the first layer reports:

- mean availability ratio;
- mean operational scarcity ratio;
- zero-availability snapshot share;
- mean equipment-unavailability ratio.

For complete zero-availability episodes it also reports the 95th percentile of
midpoint duration estimates. If fewer than 20 complete episodes exist, this is
a preliminary descriptive percentile without a confidence interval.

`zero_availability_snapshot_share` remains a snapshot statistic. It is not
renamed to `p_zero_availability`, because a time-weighted probability estimator
has not yet been approved.

## Uncertainty

Snapshot-level confidence intervals use a 95% nonparametric local-calendar-day
block bootstrap. Complete days are resampled as blocks so that neighbouring
five-minute observations are not treated as independent measurements.

The implementation uses a fixed random seed and records:

- bootstrap method;
- number of repetitions;
- confidence level.

The default is 1,000 repetitions. Tests may use a lower number to keep the test
suite fast.

The episode-duration percentile uses an IID bootstrap over complete episodes.
This is reported separately because its sample-size requirement differs from
the snapshot statistics.

## Current limitations

- Source-native OCPI locations are analysed independently.
- DATEX evidence is not pooled with OCPI.
- Day-block intervals do not correct for systematic source bias.
- The initial thresholds have not yet been empirically calibrated.
- No multiple-site or citywide weighting scheme is defined.
- No weekday/weekend or hour-of-day profile is estimated yet.
- No causal interpretation is permitted.

## Presentation rule

Until a result is statistically qualified, presentation language must say
`preliminary observed value in the currently collected window`. Once qualified,
the estimate may be shown with its collection window, sample size, coverage and
95% confidence interval. Neither form is evidence of a physical queue.
