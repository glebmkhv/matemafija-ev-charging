# matemafija-ev-charging
Data collection and adaptive congestion pricing for the Vilnius EV charging network. Hack4Vilnius Challenge 13.

## Near-real-time collection

The collector stores OCPI locations and DATEX II dynamic statuses every five
minutes. OCPI tariffs, sanitized credentials metadata and DATEX II static data
are refreshed daily.

```bash
python src/collect.py
```

One complete collection cycle:

```bash
python src/collect.py --once
```

The source-native database design and reconciliation rules are documented in
[`docs/database_v2.md`](docs/database_v2.md).

The provenance, definitions and permitted uses of observed, reconstructed,
estimated and policy variables are defined in
[`docs/variable_dictionary.md`](docs/variable_dictionary.md).

Observable evidence of charging-capacity scarcity, its censoring rules and its
limits are defined in [`docs/scarcity_metrics.md`](docs/scarcity_metrics.md).

Qualification thresholds and uncertainty estimation for the first derivative
statistics are documented in
[`docs/derivative_statistics.md`](docs/derivative_statistics.md).

The versioned inputs, execution modes, events, outputs and claim boundaries of
the common fixed/adaptive evaluation environment are defined in
[`docs/simulator_contract.md`](docs/simulator_contract.md).

## Database exploration dashboard

Start collection and the dashboard together:

```bash
python src/collect.py --dashboard
```

Or open the dashboard without starting a collector:

```bash
python -m streamlit run src/dashboard.py
```

The dashboard reads the source-native v2 tables in read-only mode and refreshes
every 30 seconds. It exposes the current OCPI and DATEX records, historical
observations, source revisions and raw payload metadata, explicit cross-source
mappings, data-quality issues, and the live SQLite schema.

It deliberately does not calculate queue length, post-charge idle time,
congestion scores, adaptive fees, cashback, or other model-derived values. The
purpose of this interface is to inspect what was actually observed, how it was
normalized, and which relationships have evidence before derived variables are
designed.
