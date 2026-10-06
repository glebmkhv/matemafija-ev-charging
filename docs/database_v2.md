# Database v2: OCPI, DATEX II and cross-source reconciliation

The database keeps three distinct kinds of information:

1. source observations exactly attributable to OCPI or DATEX II;
2. explicit, revisable mappings between source entities;
3. derived or simulated information, which must never be presented as source data.

## Collection cadence

| Endpoint | Default cadence | Stored as |
|---|---:|---|
| OCPI locations | 5 minutes | complete current snapshot and EVSE observations |
| OCPI tariffs | 24 hours | complete current snapshot and versioned structure |
| OCPI credentials metadata | 24 hours | sanitized roles and business metadata; never tokens |
| DATEX II EnergyInfrastructureTablePublication | 24 hours | complete static snapshot |
| DATEX II EnergyInfrastructureStatusPublication | 5 minutes | immutable status observations |

Every request has a `collection_runs` record. A full snapshot can mark an entity
missing only after the run finishes successfully. Raw payloads are stored with
gzip compression and an SHA-256 digest so future parser versions can reproduce
the normalized data.

## Time semantics

- `source_last_updated_raw`: the unmodified source value.
- `source_last_updated_utc`: a parsed UTC value, or `NULL` when parsing fails.
- `server_publication_time_*`: DATEX publication time.
- `observed_at`: when the collector observed the value.
- `first_seen_at` and `last_seen_at`: bounds of collector observation.
- `missing_since`: the first successful complete snapshot in which the entity
  was absent.
- `valid_from` and `valid_to`: validity of a relationship or mapping in this
  database, not a claim about physical-world validity before observation.

## Identity

Source identities are scoped by data source and protocol identifiers. Missing
required identity components raise an error; they are never replaced by a shared
`UNKNOWN` identifier.

DATEX connectors currently have no public connector identifier. Their database
identity therefore includes their refill point and XML ordinal. The original
content fingerprint is retained, and the ordinal is not presented as a public ID.

## Revisions and observations

`source_entity_revisions` deduplicates normalized content. The separate
`source_entity_observations` table records every run in which a revision was
seen. Therefore an `A -> B -> A` sequence remains reconstructable even when the
same `A` content is reused.

## Mapping rules

Source-native entities are never merged destructively.

- OCPI locations and DATEX stations can be linked through the shared numeric
  identifier plus coordinate evidence.
- DATEX refill point IDs can identify groups of OCPI EVSEs after removal of the
  `LT-` prefix and comparison with OCPI public EVSE identifiers.
- A DATEX dynamic status is linked by ordinal only when its station's dynamic
  count equals the static connector count or refill point count. These links use
  confidence below 1 and retain their evidence.
- Count disagreement produces a data-quality issue and no forced equipment link.

All mappings include relation type, cardinality, method, algorithm version,
confidence, evidence, review state, manual-verification state, and validity
interval. A later mapping algorithm can supersede an unverified mapping without
rewriting source history.

## Units and missing values

OCPI electrical units are stored in explicitly named columns such as
`max_electric_power_w`. DATEX `maxPowerAtSocket` is retained as raw text and is
also interpreted as kilowatts with an explicit `unit_interpretation_status`.

Missing, `null`, empty list, empty string, zero and source `UNKNOWN` values are
not intentionally collapsed. Monetary decimals are stored as text to avoid
binary floating-point rounding.

## Security

The public credentials endpoint can expose a `token` field. Token-, secret- and
authorization-named fields are replaced recursively with `[REDACTED]` before
the raw metadata payload is persisted. Authentication secrets must remain in
environment variables or a system keychain.

