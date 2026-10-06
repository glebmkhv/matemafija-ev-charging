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
[`docs/database_v2.md`](docs/database_v2.md). The current dashboard still uses
the legacy compatibility tables; the collector dual-writes OCPI data there until
the dashboard is migrated in the next step.
