# Local data

The collector creates `data/ev_charging.db`. SQLite databases, WAL/SHM files and
raw downloads are intentionally excluded from Git because they are large,
continuously changing runtime artifacts—not a reproducible release dataset.

Initialize the database with one public-source collection cycle:

```bash
python src/collect.py --once
```

Then open either read-only interface:

```bash
python -m streamlit run src/policy_dashboard.py
python -m streamlit run src/dashboard.py
```

## Publication rule

Do not commit or upload the working database without a separate data-release
review. Although the feeds are public and credentials metadata is sanitized,
a release should still document its collection window, source terms, schema
version, checksums, provenance and any applicable redistribution conditions.

Small reviewed public fixtures may be added under `data/samples/` in the
future. Tests currently construct isolated temporary databases and do not need
the local collected database.
