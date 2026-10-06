"""Versioned, provenance-preserving OCPI and DATEX II persistence."""

from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "ev_charging.db"
LEGACY_SCHEMA_PATH = PROJECT_ROOT / "src" / "schema.sql"
SCHEMA_PATH = PROJECT_ROOT / "src" / "schema_v2.sql"
COLLECTOR_VERSION = "2.0.0"
PARSER_VERSION = "2.0.0"

OCPI_BASE_URL = "https://ev.vialietuva.lt/ocpi/2.3.0"
DATEX_BASE_URL = "https://ev.vialietuva.lt/publicdata"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_bytes(value):
    return sha256(value).hexdigest()


def _hash_text(value):
    return _hash_bytes(value.encode("utf-8"))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value):
    if value is None or value == "":
        return None
    candidate = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_text(value):
    parsed = _parse_time(value)
    return parsed.isoformat() if parsed else None


def _float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _required_identity(*parts):
    if any(part is None or str(part).strip() == "" for part in parts):
        raise ValueError(f"Missing required identity component: {parts!r}")
    return "|".join(str(part) for part in parts)


def connect_database(database_path=DATABASE_PATH):
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def create_database(database_path=DATABASE_PATH):
    """Create legacy compatibility tables and the complete v2 schema."""
    connection = connect_database(database_path)
    try:
        if LEGACY_SCHEMA_PATH.exists():
            connection.executescript(LEGACY_SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _seed_sources(connection)
        connection.commit()
    finally:
        connection.close()


def _seed_sources(connection):
    created_at = _now()
    sources = [
        ("VIA_LIETUVA_OCPI", "OCPI", "2.3.0", "Via Lietuva", "LT", None, OCPI_BASE_URL),
        ("VIA_LIETUVA_DATEX", "DATEX_II", "3", "Via Lietuva", "LT", "lakd", DATEX_BASE_URL),
    ]
    for row in sources:
        connection.execute(
            """
            INSERT INTO data_sources (
                source_code, protocol, protocol_version, publisher_name,
                country_code, national_identifier, base_url, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_code) DO UPDATE SET
                protocol_version=excluded.protocol_version,
                publisher_name=excluded.publisher_name,
                country_code=excluded.country_code,
                national_identifier=excluded.national_identifier,
                base_url=excluded.base_url
            """,
            (*row, created_at),
        )
    endpoint_rows = [
        ("VIA_LIETUVA_OCPI", "ocpi_locations", f"{OCPI_BASE_URL}/locations", "JSON", 300, 1, 1),
        ("VIA_LIETUVA_OCPI", "ocpi_tariffs", f"{OCPI_BASE_URL}/tariffs", "JSON", 86400, 1, 0),
        ("VIA_LIETUVA_OCPI", "ocpi_credentials_metadata", f"{OCPI_BASE_URL}/credentials", "JSON", 86400, 1, 0),
        ("VIA_LIETUVA_DATEX", "datex_energy_infrastructure_table", f"{DATEX_BASE_URL}/EnergyInfrastructureTablePublication", "XML", 86400, 1, 0),
        ("VIA_LIETUVA_DATEX", "datex_energy_infrastructure_status", f"{DATEX_BASE_URL}/EnergyInfrastructureStatusPublication", "XML", 300, 1, 1),
    ]
    for source_code, endpoint_type, url, format_name, frequency, full, dynamic in endpoint_rows:
        source_id = connection.execute(
            "SELECT data_source_id FROM data_sources WHERE source_code=?", (source_code,)
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO source_endpoints (
                data_source_id, endpoint_type, endpoint_url, expected_format,
                collection_frequency_seconds, is_full_snapshot, contains_dynamic_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(data_source_id, endpoint_type) DO UPDATE SET
                endpoint_url=excluded.endpoint_url,
                expected_format=excluded.expected_format,
                collection_frequency_seconds=excluded.collection_frequency_seconds,
                is_full_snapshot=excluded.is_full_snapshot,
                contains_dynamic_data=excluded.contains_dynamic_data
            """,
            (source_id, endpoint_type, url, format_name, frequency, full, dynamic),
        )


def _source_and_endpoint(connection, source_code, endpoint_type):
    row = connection.execute(
        """
        SELECT data_sources.data_source_id, source_endpoints.source_endpoint_id,
               source_endpoints.endpoint_url
        FROM data_sources JOIN source_endpoints USING (data_source_id)
        WHERE data_sources.source_code=? AND source_endpoints.endpoint_type=?
        """,
        (source_code, endpoint_type),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown source endpoint {source_code}/{endpoint_type}")
    return row


def _start_run(connection, endpoint, collected_at, run_id=None, parameters=None):
    run_id = run_id or str(uuid4())
    connection.execute(
        """
        INSERT INTO collection_runs (
            collection_run_id, source_endpoint_id, started_at, run_status,
            requested_url, request_parameters_json, collector_version
        ) VALUES (?, ?, ?, 'running', ?, ?, ?)
        """,
        (run_id, endpoint["source_endpoint_id"], collected_at,
         endpoint["endpoint_url"], _json(parameters) if parameters is not None else None,
         COLLECTOR_VERSION),
    )
    return run_id


def _finish_run(connection, run_id, *, collected_at, records, payload_hash,
                publication_time=None, http_status=200):
    connection.execute(
        """
        UPDATE collection_runs SET completed_at=?, run_status='success',
            is_complete_snapshot=1, http_status=?, pages_received=1,
            records_received=?, records_accepted=?, payload_sha256=?,
            server_publication_time_raw=?, server_publication_time_utc=?
        WHERE collection_run_id=?
        """,
        (collected_at, http_status, records, records, payload_hash,
         publication_time, _utc_text(publication_time), run_id),
    )


def _save_raw_payload(connection, run_id, payload_bytes, collected_at,
                      content_type):
    digest = _hash_bytes(payload_bytes)
    compressed_payload = gzip.compress(payload_bytes, compresslevel=6)
    cursor = connection.execute(
        """
        INSERT INTO raw_payloads (
            collection_run_id, content_type, content_encoding, payload_sha256,
            payload_bytes, retrieved_at, parser_version
        ) VALUES (?, ?, 'gzip', ?, ?, ?, ?)
        """,
        (run_id, content_type, digest, compressed_payload, collected_at, PARSER_VERSION),
    )
    return cursor.lastrowid, digest


def _revision(connection, source_id, entity_type, entity_key, content,
              source_last_updated, collected_at, run_id):
    normalized = _json(content)
    digest = _hash_text(normalized)
    connection.execute(
        """
        INSERT OR IGNORE INTO source_entity_revisions (
            data_source_id, source_entity_type, source_entity_key,
            content_sha256, source_last_updated_raw, source_last_updated_utc,
            normalized_content_json, raw_content, parser_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (source_id, entity_type, entity_key, digest, source_last_updated,
         _utc_text(source_last_updated), normalized, normalized,
         PARSER_VERSION, collected_at),
    )
    revision_id = connection.execute(
        """
        SELECT source_entity_revision_id FROM source_entity_revisions
        WHERE data_source_id=? AND source_entity_type=?
          AND source_entity_key=? AND content_sha256=?
        """,
        (source_id, entity_type, entity_key, digest),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT OR IGNORE INTO source_entity_observations (
            collection_run_id, source_entity_revision_id, observed_at
        ) VALUES (?, ?, ?)
        """,
        (run_id, revision_id, collected_at),
    )
    return revision_id


def _canonical_status(value):
    if value is None or not str(value).strip():
        return "unknown"
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _quality_for_timestamp(source_time, observed_at):
    source = _parse_time(source_time)
    observed = _parse_time(observed_at)
    if source is None or observed is None:
        return None, "missing_or_invalid"
    age = (observed - source).total_seconds()
    if age < -5:
        return age, "future"
    if age > 30 * 86400:
        return age, "older_than_30_days"
    if age > 86400:
        return age, "older_than_24_hours"
    return age, "current"


def _quality_issue(connection, run_id, entity_type, entity_key, field_path,
                   code, severity, raw_value, description, detected_at):
    connection.execute(
        """INSERT INTO data_quality_issues (
           collection_run_id, source_entity_type, source_entity_key,
           field_path, issue_code, severity, raw_value, issue_description,
           detected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, entity_type, entity_key, field_path, code, severity,
         str(raw_value) if raw_value is not None else None, description, detected_at),
    )


def save_ocpi_locations_snapshot(locations, database_path=DATABASE_PATH,
                                 collected_at=None, collection_run_id=None):
    """Persist a complete OCPI locations snapshot without losing null/empty distinctions."""
    create_database(database_path)
    collected_at = collected_at or _now()
    payload_bytes = _json(locations).encode("utf-8")
    connection = connect_database(database_path)
    try:
        with connection:
            endpoint = _source_and_endpoint(connection, "VIA_LIETUVA_OCPI", "ocpi_locations")
            source_id = endpoint["data_source_id"]
            run_id = _start_run(connection, endpoint, collected_at, collection_run_id)
            _, payload_hash = _save_raw_payload(connection, run_id, payload_bytes,
                                                collected_at, "application/json")
            seen_locations, seen_evses, seen_connectors = set(), set(), set()
            for location in locations:
                location_key = _required_identity(
                    "ocpi-location", source_id, location.get("country_code"),
                    location.get("party_id"), location.get("id"))
                seen_locations.add(location_key)
                location_content = {key: value for key, value in location.items() if key != "evses"}
                location_revision = _revision(
                    connection, source_id, "ocpi_location", location_key,
                    location_content, location.get("last_updated"), collected_at, run_id)
                coordinates = location.get("coordinates") or {}
                connection.execute(
                    """
                    INSERT INTO ocpi_locations (
                        ocpi_location_key, data_source_id, country_code, party_id,
                        source_location_id, publish, name, address, city, postal_code,
                        state, country, latitude_raw, longitude_raw, latitude, longitude,
                        parking_type, time_zone, charging_when_closed, help_phone,
                        help_email, source_last_updated_raw, source_last_updated_utc,
                        first_seen_at, last_seen_at, missing_since, is_current,
                        current_revision_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?)
                    ON CONFLICT(ocpi_location_key) DO UPDATE SET
                        publish=excluded.publish, name=excluded.name, address=excluded.address,
                        city=excluded.city, postal_code=excluded.postal_code, state=excluded.state,
                        country=excluded.country, latitude_raw=excluded.latitude_raw,
                        longitude_raw=excluded.longitude_raw, latitude=excluded.latitude,
                        longitude=excluded.longitude, parking_type=excluded.parking_type,
                        time_zone=excluded.time_zone,
                        charging_when_closed=excluded.charging_when_closed,
                        help_phone=excluded.help_phone, help_email=excluded.help_email,
                        source_last_updated_raw=excluded.source_last_updated_raw,
                        source_last_updated_utc=excluded.source_last_updated_utc,
                        last_seen_at=excluded.last_seen_at, missing_since=NULL, is_current=1,
                        current_revision_id=excluded.current_revision_id
                    """,
                    (location_key, source_id, location.get("country_code"), location.get("party_id"),
                     str(location.get("id")), location.get("publish"), location.get("name"),
                     location.get("address"), location.get("city"), location.get("postal_code"),
                     location.get("state"), location.get("country"), coordinates.get("latitude"),
                     coordinates.get("longitude"), _float(coordinates.get("latitude")),
                     _float(coordinates.get("longitude")), location.get("parking_type"),
                     location.get("time_zone"), location.get("charging_when_closed"),
                     location.get("help_phone"), location.get("help_email"),
                     location.get("last_updated"), _utc_text(location.get("last_updated")),
                     collected_at, collected_at, location_revision),
                )
                _save_ocpi_location_children(connection, location, location_key,
                                             location_revision, source_id, collected_at)
                for evse in location.get("evses") or []:
                    try:
                        evse_key = _save_ocpi_evse(
                            connection, location, location_key, evse,
                            source_id, collected_at, run_id
                        )
                    except ValueError as error:
                        _quality_issue(
                            connection, run_id, "ocpi_evse",
                            evse.get("evse_id") or evse.get("uid"), "uid",
                            "OCPI_MISSING_REQUIRED_EVSE_IDENTITY", "error",
                            _json(evse), str(error), collected_at,
                        )
                        continue
                    seen_evses.add(evse_key)
                    for connector_index, connector in enumerate(evse.get("connectors") or []):
                        connector_key = _save_ocpi_connector(
                            connection, location, evse_key, connector, connector_index,
                            source_id, collected_at, run_id)
                        seen_connectors.add(connector_key)
            _mark_missing(connection, "ocpi_locations", "ocpi_location_key", seen_locations, collected_at)
            _mark_missing(connection, "ocpi_evses", "ocpi_evse_key", seen_evses, collected_at)
            _mark_missing(connection, "ocpi_connectors", "ocpi_connector_key", seen_connectors, collected_at)
            _finish_run(connection, run_id, collected_at=collected_at,
                        records=len(locations), payload_hash=payload_hash)
            refresh_cross_source_mappings(connection, collected_at)
        return {"collection_run_id": run_id, "locations": len(seen_locations),
                "evses": len(seen_evses), "connectors": len(seen_connectors)}
    finally:
        connection.close()


def _save_ocpi_location_children(connection, location, location_key,
                                 revision_id, source_id, collected_at):
    for role in ("operator", "owner", "suboperator"):
        organization = location.get(role)
        if not organization or not organization.get("name"):
            continue
        organization_key = _required_identity(
            "ocpi-organization", source_id,
            organization.get("name").strip().casefold())
        connection.execute(
            """INSERT INTO ocpi_organizations VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(ocpi_organization_key) DO UPDATE SET
               organization_name=excluded.organization_name, website=excluded.website,
               last_seen_at=excluded.last_seen_at, is_current=1""",
            (organization_key, source_id, organization.get("name"), organization.get("website"),
             collected_at, collected_at),
        )
        current = connection.execute(
            """SELECT 1 FROM ocpi_location_organization_roles
               WHERE ocpi_location_key=? AND ocpi_organization_key=?
                 AND organization_role=? AND is_current=1""",
            (location_key, organization_key, role),
        ).fetchone()
        if current is None:
            connection.execute(
                """UPDATE ocpi_location_organization_roles SET is_current=0, valid_to=?
                   WHERE ocpi_location_key=? AND organization_role=? AND is_current=1""",
                (collected_at, location_key, role),
            )
            connection.execute(
                """INSERT INTO ocpi_location_organization_roles
                   VALUES (?, ?, ?, ?, NULL, 1)""",
                (location_key, organization_key, role, collected_at),
            )
    for index, direction in enumerate(location.get("directions") or []):
        connection.execute("INSERT OR IGNORE INTO ocpi_location_directions VALUES (?, ?, ?, ?)",
                           (revision_id, index, direction.get("language"), direction.get("text")))
    for index, facility in enumerate(location.get("facilities") or []):
        connection.execute("INSERT OR IGNORE INTO ocpi_location_facilities VALUES (?, ?, ?)",
                           (revision_id, index, facility))
    for index, image in enumerate(location.get("images") or []):
        connection.execute(
            "INSERT OR IGNORE INTO ocpi_location_images VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (revision_id, index, image.get("url"), image.get("thumbnail"),
             image.get("category"), image.get("type"), _integer(image.get("width")),
             _integer(image.get("height"))),
        )
    opening = location.get("opening_times")
    if opening is not None:
        connection.execute("INSERT OR IGNORE INTO ocpi_location_opening_times VALUES (?, ?)",
                           (revision_id, opening.get("twentyfourseven")))
        for index, period in enumerate(opening.get("regular_hours") or []):
            connection.execute(
                "INSERT OR IGNORE INTO ocpi_location_regular_hours VALUES (?, ?, ?, ?, ?)",
                (revision_id, index, _integer(period.get("weekday")),
                 period.get("period_begin"), period.get("period_end")),
            )
    for parking_index, parking in enumerate(location.get("parking_places") or []):
        parking_key = _required_identity("ocpi-parking", location_key, parking.get("id"))
        connection.execute(
            """INSERT INTO ocpi_parking_places VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(ocpi_parking_place_key) DO UPDATE SET
               reservation_required=excluded.reservation_required,
               restricted_to_type=excluded.restricted_to_type,
               standards=excluded.standards, current_revision_id=excluded.current_revision_id""",
            (parking_key, location_key, str(parking.get("id")), parking.get("reservation_required"),
             parking.get("restricted_to_type"), parking.get("standards"), revision_id),
        )
        for vehicle_index, vehicle_type in enumerate(parking.get("vehicle_types") or []):
            connection.execute(
                "INSERT OR IGNORE INTO ocpi_parking_place_vehicle_types VALUES (?, ?, ?, ?)",
                (revision_id, parking_index, vehicle_index, vehicle_type),
            )
    energy_mix = location.get("energy_mix")
    if isinstance(energy_mix, dict):
        energy_mix = energy_mix.get("energy_sources") or []
    for index, energy_source in enumerate(energy_mix or []):
        connection.execute(
            "INSERT OR IGNORE INTO ocpi_location_energy_mix VALUES (?, ?, ?, ?)",
            (revision_id, index, energy_source.get("source"),
             str(energy_source.get("percentage")) if energy_source.get("percentage") is not None else None),
        )


def _save_ocpi_evse(connection, location, location_key, evse, source_id,
                    collected_at, run_id):
    uid = evse.get("uid")
    evse_key = _required_identity("ocpi-evse", source_id,
                                  location.get("country_code"), location.get("party_id"), uid)
    content = {key: value for key, value in evse.items() if key != "connectors"}
    revision_id = _revision(connection, source_id, "ocpi_evse", evse_key, content,
                            evse.get("last_updated"), collected_at, run_id)
    status_raw = evse.get("status") or "UNKNOWN"
    connection.execute(
        """INSERT INTO ocpi_evses (
           ocpi_evse_key, ocpi_location_key, source_uid, public_evse_id,
           physical_reference, source_status_raw, source_status_canonical,
           source_last_updated_raw, source_last_updated_utc, first_seen_at,
           last_seen_at, missing_since, is_current, current_revision_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?)
           ON CONFLICT(ocpi_evse_key) DO UPDATE SET
           ocpi_location_key=excluded.ocpi_location_key, public_evse_id=excluded.public_evse_id,
           physical_reference=excluded.physical_reference,
           source_status_raw=excluded.source_status_raw,
           source_status_canonical=excluded.source_status_canonical,
           source_last_updated_raw=excluded.source_last_updated_raw,
           source_last_updated_utc=excluded.source_last_updated_utc,
           last_seen_at=excluded.last_seen_at, missing_since=NULL, is_current=1,
           current_revision_id=excluded.current_revision_id""",
        (evse_key, location_key, str(uid), evse.get("evse_id"), evse.get("physical_reference"),
         status_raw, _canonical_status(status_raw), evse.get("last_updated"),
         _utc_text(evse.get("last_updated")), collected_at, collected_at, revision_id),
    )
    for index, capability in enumerate(evse.get("capabilities") or []):
        connection.execute("INSERT OR IGNORE INTO ocpi_evse_capabilities VALUES (?, ?, ?)",
                           (revision_id, index, capability))
    for index, restriction in enumerate(evse.get("parking_restrictions") or []):
        connection.execute("INSERT OR IGNORE INTO ocpi_evse_parking_restrictions VALUES (?, ?, ?)",
                           (revision_id, index, restriction))
    for index, assignment in enumerate(evse.get("parking") or []):
        connection.execute("INSERT OR IGNORE INTO ocpi_evse_parking_assignments VALUES (?, ?, ?, ?)",
                           (revision_id, index, assignment.get("parking_id"),
                            _json(assignment.get("evse_position"))))
    age, quality = _quality_for_timestamp(evse.get("last_updated"), collected_at)
    connection.execute(
        """INSERT INTO ocpi_evse_status_observations (
           collection_run_id, ocpi_evse_key, observed_at, source_last_updated_raw,
           source_last_updated_utc, status_raw, status_canonical,
           source_timestamp_age_seconds, source_timestamp_quality)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, evse_key, collected_at, evse.get("last_updated"),
         _utc_text(evse.get("last_updated")), status_raw, _canonical_status(status_raw),
         age, quality),
    )
    return evse_key


def _save_ocpi_connector(connection, location, evse_key, connector,
                         connector_index, source_id, collected_at, run_id):
    source_connector_id = connector.get("id")
    if source_connector_id is None:
        source_connector_id = f"missing-source-id-at-index-{connector_index}"
    connector_key = _required_identity("ocpi-connector", evse_key, source_connector_id)
    revision_id = _revision(connection, source_id, "ocpi_connector", connector_key,
                            connector, connector.get("last_updated"), collected_at, run_id)
    connection.execute(
        """INSERT INTO ocpi_connectors (
           ocpi_connector_key, ocpi_evse_key, source_connector_id,
           connector_standard, connector_format, power_type, voltage_v,
           amperage_a, max_electric_power_w, terms_and_conditions_url,
           source_last_updated_raw, source_last_updated_utc, first_seen_at,
           last_seen_at, missing_since, is_current, current_revision_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?)
           ON CONFLICT(ocpi_connector_key) DO UPDATE SET
           connector_standard=excluded.connector_standard,
           connector_format=excluded.connector_format, power_type=excluded.power_type,
           voltage_v=excluded.voltage_v, amperage_a=excluded.amperage_a,
           max_electric_power_w=excluded.max_electric_power_w,
           terms_and_conditions_url=excluded.terms_and_conditions_url,
           source_last_updated_raw=excluded.source_last_updated_raw,
           source_last_updated_utc=excluded.source_last_updated_utc,
           last_seen_at=excluded.last_seen_at, missing_since=NULL, is_current=1,
           current_revision_id=excluded.current_revision_id""",
        (connector_key, evse_key, str(source_connector_id), connector.get("standard"),
         connector.get("format"), connector.get("power_type"), _float(connector.get("voltage")),
         _float(connector.get("amperage")), _float(connector.get("max_electric_power")),
         connector.get("terms_and_conditions"), connector.get("last_updated"),
         _utc_text(connector.get("last_updated")), collected_at, collected_at, revision_id),
    )
    for index, capability in enumerate(connector.get("capabilities") or []):
        connection.execute("INSERT OR IGNORE INTO ocpi_connector_capabilities VALUES (?, ?, ?)",
                           (revision_id, index, capability))
    desired = {
        _required_identity("ocpi-tariff", source_id, location.get("country_code"),
                           location.get("party_id"), tariff_id)
        for tariff_id in connector.get("tariff_ids") or []
    }
    active = {row[0] for row in connection.execute(
        "SELECT ocpi_tariff_key FROM ocpi_connector_tariff_assignments WHERE ocpi_connector_key=? AND is_current=1",
        (connector_key,))}
    for tariff_key in active - desired:
        connection.execute(
            "UPDATE ocpi_connector_tariff_assignments SET is_current=0, valid_to=?, last_seen_at=? WHERE ocpi_connector_key=? AND ocpi_tariff_key=? AND is_current=1",
            (collected_at, collected_at, connector_key, tariff_key))
    for tariff_key in desired:
        if tariff_key in active:
            connection.execute(
                "UPDATE ocpi_connector_tariff_assignments SET last_seen_at=? WHERE ocpi_connector_key=? AND ocpi_tariff_key=? AND is_current=1",
                (collected_at, connector_key, tariff_key))
        else:
            connection.execute(
                "INSERT INTO ocpi_connector_tariff_assignments VALUES (?, ?, ?, NULL, ?, ?, 1)",
                (connector_key, tariff_key, collected_at, collected_at, collected_at))
    return connector_key


def _mark_missing(connection, table, key_column, seen, collected_at):
    rows = connection.execute(f"SELECT {key_column} FROM {table} WHERE is_current=1").fetchall()
    for row in rows:
        if row[0] not in seen:
            connection.execute(
                f"UPDATE {table} SET is_current=0, missing_since=COALESCE(missing_since, ?) WHERE {key_column}=?",
                (collected_at, row[0]))


def save_ocpi_tariffs_snapshot(tariffs, database_path=DATABASE_PATH,
                               collected_at=None, collection_run_id=None):
    create_database(database_path)
    collected_at = collected_at or _now()
    payload_bytes = _json(tariffs).encode("utf-8")
    connection = connect_database(database_path)
    try:
        with connection:
            endpoint = _source_and_endpoint(connection, "VIA_LIETUVA_OCPI", "ocpi_tariffs")
            source_id = endpoint["data_source_id"]
            run_id = _start_run(connection, endpoint, collected_at, collection_run_id)
            _, payload_hash = _save_raw_payload(connection, run_id, payload_bytes,
                                                collected_at, "application/json")
            seen = set()
            for tariff in tariffs:
                tariff_key = _required_identity("ocpi-tariff", source_id,
                                                tariff.get("country_code"), tariff.get("party_id"), tariff.get("id"))
                seen.add(tariff_key)
                revision_id = _revision(connection, source_id, "ocpi_tariff", tariff_key,
                                        tariff, tariff.get("last_updated"), collected_at, run_id)
                connection.execute(
                    """INSERT INTO ocpi_tariffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?)
                       ON CONFLICT(ocpi_tariff_key) DO UPDATE SET
                       tariff_name=excluded.tariff_name, currency=excluded.currency,
                       tariff_alternative_url=excluded.tariff_alternative_url,
                       minimum_price_raw=excluded.minimum_price_raw,
                       maximum_price_raw=excluded.maximum_price_raw,
                       start_date_time_raw=excluded.start_date_time_raw,
                       end_date_time_raw=excluded.end_date_time_raw,
                       tax_included_raw=excluded.tax_included_raw,
                       source_last_updated_raw=excluded.source_last_updated_raw,
                       source_last_updated_utc=excluded.source_last_updated_utc,
                       last_seen_at=excluded.last_seen_at, missing_since=NULL, is_current=1,
                       current_revision_id=excluded.current_revision_id""",
                    (tariff_key, source_id, tariff.get("country_code"), tariff.get("party_id"),
                     str(tariff.get("id")), tariff.get("name"), tariff.get("currency"),
                     tariff.get("tariff_alt_url"), _json(tariff.get("min_price")),
                     _json(tariff.get("max_price")), tariff.get("start_date_time"),
                     tariff.get("end_date_time"), str(tariff.get("tax_included")) if tariff.get("tax_included") is not None else None,
                     tariff.get("last_updated"), _utc_text(tariff.get("last_updated")),
                     collected_at, collected_at, revision_id),
                )
                _save_tariff_children(connection, tariff, revision_id)
            _mark_missing(connection, "ocpi_tariffs", "ocpi_tariff_key", seen, collected_at)
            _finish_run(connection, run_id, collected_at=collected_at,
                        records=len(seen), payload_hash=payload_hash)
        return {"collection_run_id": run_id, "tariffs": len(seen)}
    finally:
        connection.close()


def _sanitize_credentials(value):
    """Remove secrets recursively while preserving the public object structure."""
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if any(word in key.casefold() for word in ("token", "secret", "authorization")):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = _sanitize_credentials(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_credentials(item) for item in value]
    return value


def save_ocpi_credentials_metadata(credentials, database_path=DATABASE_PATH,
                                   collected_at=None, collection_run_id=None):
    """Store roles and business metadata without persisting authentication tokens."""
    create_database(database_path)
    collected_at = collected_at or _now()
    sanitized = _sanitize_credentials(credentials)
    payload_bytes = _json(sanitized).encode("utf-8")
    connection = connect_database(database_path)
    try:
        with connection:
            endpoint = _source_and_endpoint(
                connection, "VIA_LIETUVA_OCPI", "ocpi_credentials_metadata"
            )
            run_id = _start_run(connection, endpoint, collected_at, collection_run_id)
            _, payload_hash = _save_raw_payload(
                connection, run_id, payload_bytes, collected_at, "application/json"
            )
            token_was_present = any(
                "token" in key.casefold() for key in credentials.keys()
            )
            metadata_id = connection.execute(
                """INSERT INTO ocpi_credentials_metadata (
                   collection_run_id, credentials_url, token_was_present,
                   sanitized_raw_json, observed_at) VALUES (?, ?, ?, ?, ?)""",
                (run_id, credentials.get("url"), int(token_was_present),
                 _json(sanitized), collected_at),
            ).lastrowid
            roles = credentials.get("roles") or []
            for index, role in enumerate(roles):
                business = role.get("business_details") or {}
                connection.execute(
                    """INSERT INTO ocpi_credential_roles VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (metadata_id, index, role.get("role"), role.get("country_code"),
                     role.get("party_id"), business.get("name"), business.get("website"),
                     _json(business.get("logo"))),
                )
            _finish_run(connection, run_id, collected_at=collected_at,
                        records=len(roles), payload_hash=payload_hash)
        return {"collection_run_id": run_id, "roles": len(roles)}
    finally:
        connection.close()


def _save_tariff_children(connection, tariff, revision_id):
    for index, text in enumerate(tariff.get("tariff_alt_text") or []):
        connection.execute("INSERT OR IGNORE INTO ocpi_tariff_alternative_texts VALUES (?, ?, ?, ?)",
                           (revision_id, index, text.get("language"), text.get("text")))
    for element_index, element in enumerate(tariff.get("elements") or []):
        connection.execute("INSERT OR IGNORE INTO ocpi_tariff_elements VALUES (?, ?)",
                           (revision_id, element_index))
        for component_index, component in enumerate(element.get("price_components") or []):
            connection.execute(
                "INSERT OR IGNORE INTO ocpi_tariff_price_components VALUES (?, ?, ?, ?, ?, ?, ?)",
                (revision_id, element_index, component_index, component.get("type"),
                 str(component.get("price")) if component.get("price") is not None else None,
                 component.get("step_size"),
                 str(component.get("vat")) if component.get("vat") is not None else None))
        restrictions = element.get("restrictions")
        if restrictions is not None:
            connection.execute(
                "INSERT OR IGNORE INTO ocpi_tariff_restrictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (revision_id, element_index, restrictions.get("start_time"), restrictions.get("end_time"),
                 restrictions.get("start_date"), restrictions.get("end_date"),
                 _float(restrictions.get("min_kwh")), _float(restrictions.get("max_kwh")),
                 _float(restrictions.get("min_power")), _float(restrictions.get("max_power")),
                 _integer(restrictions.get("min_duration")), _integer(restrictions.get("max_duration")),
                 restrictions.get("reservation"), _json(restrictions)))
            for day_index, day in enumerate(restrictions.get("day_of_week") or []):
                connection.execute("INSERT OR IGNORE INTO ocpi_tariff_restriction_days VALUES (?, ?, ?, ?)",
                                   (revision_id, element_index, day_index, day))


def save_datex_static_publication(parsed, payload_bytes, database_path=DATABASE_PATH,
                                  collected_at=None, collection_run_id=None,
                                  http_status=200):
    create_database(database_path)
    collected_at = collected_at or _now()
    connection = connect_database(database_path)
    try:
        with connection:
            endpoint = _source_and_endpoint(connection, "VIA_LIETUVA_DATEX", "datex_energy_infrastructure_table")
            source_id = endpoint["data_source_id"]
            run_id = _start_run(connection, endpoint, collected_at, collection_run_id)
            payload_id, payload_hash = _save_raw_payload(connection, run_id, payload_bytes,
                                                         collected_at, "application/xml")
            publication_id = connection.execute(
                """INSERT INTO datex_static_publications (
                   collection_run_id, publication_type, language, model_base_version,
                   schema_location, feed_description, publication_time_raw,
                   publication_time_utc, publication_creator_country,
                   publication_creator_national_identifier, raw_payload_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, parsed.get("publication_type"), parsed.get("language"),
                 parsed.get("model_base_version"), parsed.get("schema_location"),
                 parsed.get("feed_description"), parsed.get("publication_time"),
                 _utc_text(parsed.get("publication_time")), parsed.get("publication_creator_country"),
                 parsed.get("publication_creator_national_identifier"), payload_id),
            ).lastrowid
            counts = _save_datex_static_entities(connection, parsed, source_id,
                                                  collected_at, run_id)
            _finish_run(connection, run_id, collected_at=collected_at,
                        records=counts["stations"], payload_hash=payload_hash,
                        publication_time=parsed.get("publication_time"), http_status=http_status)
            refresh_cross_source_mappings(connection, collected_at)
        return {"collection_run_id": run_id, **counts}
    finally:
        connection.close()


def _save_datex_static_entities(connection, parsed, source_id, collected_at, run_id):
    table = parsed["energy_infrastructure_table"]
    table_key = _required_identity("datex-table", source_id, table.get("id"))
    table_revision = _revision(connection, source_id, "datex_table", table_key,
                               {k: v for k, v in table.items() if k != "sites"},
                               None, collected_at, run_id)
    connection.execute(
        """INSERT INTO datex_energy_infrastructure_tables VALUES (?, ?, ?, ?, ?, ?, 1, ?)
           ON CONFLICT(datex_table_key) DO UPDATE SET source_version=excluded.source_version,
           last_seen_at=excluded.last_seen_at, is_current=1,
           current_revision_id=excluded.current_revision_id""",
        (table_key, source_id, table.get("id"), table.get("version"),
         collected_at, collected_at, table_revision))
    seen_sites, seen_stations, seen_refills, seen_connectors = set(), set(), set(), set()
    for site in table.get("sites") or []:
        site_key = _required_identity("datex-site", source_id, site.get("id"))
        seen_sites.add(site_key)
        site_revision = _revision(connection, source_id, "datex_site", site_key,
                                  {k: v for k, v in site.items() if k != "stations"},
                                  None, collected_at, run_id)
        connection.execute(
            """INSERT INTO datex_energy_infrastructure_sites VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 1, ?)
               ON CONFLICT(datex_site_key) DO UPDATE SET datex_table_key=excluded.datex_table_key,
               source_version=excluded.source_version, last_seen_at=excluded.last_seen_at,
               missing_since=NULL, is_current=1, current_revision_id=excluded.current_revision_id""",
            (site_key, table_key, source_id, site.get("id"), site.get("version"),
             collected_at, collected_at, site_revision))
        for station in site.get("stations") or []:
            station_key = _save_datex_station(connection, station, site_key, source_id,
                                              collected_at, run_id, seen_refills, seen_connectors)
            seen_stations.add(station_key)
    _mark_missing(connection, "datex_energy_infrastructure_sites", "datex_site_key", seen_sites, collected_at)
    _mark_missing(connection, "datex_energy_infrastructure_stations", "datex_station_key", seen_stations, collected_at)
    _mark_missing(connection, "datex_refill_points", "datex_refill_point_key", seen_refills, collected_at)
    _mark_missing(connection, "datex_connectors", "datex_connector_key", seen_connectors, collected_at)
    return {"sites": len(seen_sites), "stations": len(seen_stations),
            "refill_points": len(seen_refills), "connectors": len(seen_connectors)}


def _save_datex_station(connection, station, site_key, source_id, collected_at,
                        run_id, seen_refills, seen_connectors):
    station_key = _required_identity("datex-station", source_id, station.get("id"))
    content = {k: v for k, v in station.items() if k not in ("refill_points", "electric_energy_mixes")}
    revision_id = _revision(connection, source_id, "datex_station", station_key,
                            content, station.get("last_updated"), collected_at, run_id)
    _, timestamp_quality = _quality_for_timestamp(station.get("last_updated"), collected_at)
    if timestamp_quality in ("future", "missing_or_invalid"):
        _quality_issue(
            connection, run_id, "datex_station", station_key, "lastUpdated",
            "DATEX_STATION_TIMESTAMP_" + timestamp_quality.upper(), "warning",
            station.get("last_updated"),
            "Station lastUpdated could not be treated as a reliable source timestamp.",
            collected_at,
        )
    connection.execute(
        """INSERT INTO datex_energy_infrastructure_stations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?)
           ON CONFLICT(datex_station_key) DO UPDATE SET datex_site_key=excluded.datex_site_key,
           source_version=excluded.source_version,
           source_last_updated_raw=excluded.source_last_updated_raw,
           source_last_updated_utc=excluded.source_last_updated_utc,
           latitude_raw=excluded.latitude_raw, longitude_raw=excluded.longitude_raw,
           latitude=excluded.latitude, longitude=excluded.longitude,
           number_of_refill_points=excluded.number_of_refill_points,
           last_seen_at=excluded.last_seen_at, missing_since=NULL, is_current=1,
           current_revision_id=excluded.current_revision_id""",
        (station_key, site_key, source_id, station.get("id"), station.get("version"),
         station.get("last_updated"), _utc_text(station.get("last_updated")),
         station.get("latitude"), station.get("longitude"), _float(station.get("latitude")),
         _float(station.get("longitude")), _integer(station.get("number_of_refill_points")),
         collected_at, collected_at, revision_id))
    _save_datex_provider(connection, station_key, station.get("energy_provider"),
                         source_id, collected_at, run_id)
    for refill in station.get("refill_points") or []:
        refill_key = _required_identity("datex-refill-point", source_id, refill.get("id"))
        seen_refills.add(refill_key)
        refill_content = {k: v for k, v in refill.items() if k != "connectors"}
        refill_revision = _revision(connection, source_id, "datex_refill_point", refill_key,
                                    refill_content, None, collected_at, run_id)
        connection.execute(
            """INSERT INTO datex_refill_points VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?)
               ON CONFLICT(datex_refill_point_key) DO UPDATE SET
               datex_station_key=excluded.datex_station_key, source_version=excluded.source_version,
               xsi_type=excluded.xsi_type, usage_type=excluded.usage_type,
               ordinal_within_station=excluded.ordinal_within_station,
               last_seen_at=excluded.last_seen_at, missing_since=NULL, is_current=1,
               current_revision_id=excluded.current_revision_id""",
            (refill_key, station_key, source_id, refill.get("id"), refill.get("version"),
             refill.get("xsi_type"), refill.get("usage_type"), refill.get("ordinal_within_station"),
             collected_at, collected_at, refill_revision))
        for connector in refill.get("connectors") or []:
            connector_key = _required_identity("datex-connector", refill_key,
                                               connector.get("connector_ordinal"))
            seen_connectors.add(connector_key)
            connector_revision = _revision(connection, source_id, "datex_connector", connector_key,
                                            connector, None, collected_at, run_id)
            fingerprint = _hash_text(_json({k: v for k, v in connector.items() if k != "connector_ordinal"}))
            connection.execute(
                """INSERT INTO datex_connectors VALUES (?, ?, ?, ?, ?, ?, ?, 'assumed_kilowatts_from_profile', ?, ?, ?, NULL, 1, ?)
                   ON CONFLICT(datex_connector_key) DO UPDATE SET
                   connector_type_raw=excluded.connector_type_raw,
                   connector_type_canonical=excluded.connector_type_canonical,
                   max_power_at_socket_raw=excluded.max_power_at_socket_raw,
                   max_power_at_socket_kw=excluded.max_power_at_socket_kw,
                   content_fingerprint=excluded.content_fingerprint,
                   last_seen_at=excluded.last_seen_at, missing_since=NULL, is_current=1,
                   current_revision_id=excluded.current_revision_id""",
                (connector_key, refill_key, connector.get("connector_ordinal"),
                 connector.get("connector_type"), _canonical_status(connector.get("connector_type")),
                 connector.get("max_power_at_socket"), _float(connector.get("max_power_at_socket")),
                 fingerprint, collected_at, collected_at, connector_revision))
    _save_datex_rates(connection, station_key, station.get("electric_energy_mixes") or [],
                      source_id, collected_at, run_id)
    return station_key


def _save_datex_provider(connection, station_key, provider, source_id,
                         collected_at, run_id):
    if not provider:
        return
    name = (provider.get("names") or [{}])[0].get("text")
    description = (provider.get("descriptions") or [{}])[0].get("text")
    organization_key = _required_identity("datex-organization", source_id,
                                          (name or "missing-name").strip().casefold())
    revision_id = _revision(connection, source_id, "datex_organization", organization_key,
                            provider, provider.get("last_updated"), collected_at, run_id)
    connection.execute(
        """INSERT INTO datex_organizations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
           ON CONFLICT(datex_organization_key) DO UPDATE SET
           organization_name=excluded.organization_name,
           organization_description=excluded.organization_description,
           link_to_general_information=excluded.link_to_general_information,
           telephone_number=excluded.telephone_number,
           source_last_updated_raw=excluded.source_last_updated_raw,
           source_last_updated_utc=excluded.source_last_updated_utc,
           last_seen_at=excluded.last_seen_at, is_current=1,
           current_revision_id=excluded.current_revision_id""",
        (organization_key, source_id, name, description,
         provider.get("link_to_general_information"), provider.get("telephone_number"),
         provider.get("last_updated"), _utc_text(provider.get("last_updated")),
         collected_at, collected_at, revision_id))
    current = connection.execute(
        """SELECT 1 FROM datex_station_organization_roles WHERE datex_station_key=?
           AND datex_organization_key=? AND organization_role='energy_provider' AND is_current=1""",
        (station_key, organization_key)).fetchone()
    if current is None:
        connection.execute(
            """UPDATE datex_station_organization_roles SET is_current=0, valid_to=?
               WHERE datex_station_key=? AND organization_role='energy_provider' AND is_current=1""",
            (collected_at, station_key))
        connection.execute(
            "INSERT INTO datex_station_organization_roles VALUES (?, ?, 'energy_provider', ?, NULL, 1)",
            (station_key, organization_key, collected_at))


def _save_datex_rates(connection, station_key, mixes, source_id, collected_at, run_id):
    for mix in mixes:
        mix_key = _required_identity("datex-energy-mix", station_key, mix.get("mix_ordinal"))
        mix_revision = _revision(connection, source_id, "datex_energy_mix", mix_key,
                                 {k: v for k, v in mix.items() if k != "rates"},
                                 None, collected_at, run_id)
        connection.execute(
            """INSERT INTO datex_electric_energy_mixes VALUES (?, ?, ?, ?)
               ON CONFLICT(datex_energy_mix_key) DO UPDATE SET
               energy_mix_index=excluded.energy_mix_index,
               current_revision_id=excluded.current_revision_id""",
            (mix_key, station_key, mix.get("energy_mix_index"), mix_revision))
        for rate in mix.get("rates") or []:
            rate_key = _required_identity("datex-rate", mix_key, rate.get("rate_ordinal"))
            rate_revision = _revision(connection, source_id, "datex_rate", rate_key,
                                      {k: v for k, v in rate.items() if k not in ("valid_periods", "pricing_policy")},
                                      None, collected_at, run_id)
            connection.execute(
                """INSERT INTO datex_rates VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(datex_rate_key) DO UPDATE SET xsi_type=excluded.xsi_type,
                   applicable_currency=excluded.applicable_currency,
                   overall_start_time_raw=excluded.overall_start_time_raw,
                   current_revision_id=excluded.current_revision_id""",
                (rate_key, mix_key, rate.get("xsi_type"), rate.get("applicable_currency"),
                 rate.get("overall_start_time"), rate_revision))
            for period in rate.get("valid_periods") or []:
                period_key = _required_identity("datex-valid-period", rate_key, period.get("period_ordinal"))
                period_revision = _revision(connection, source_id, "datex_valid_period", period_key,
                                             period, None, collected_at, run_id)
                if period.get("xml_namespace_status") == "unqualified_namespace":
                    _quality_issue(
                        connection, run_id, "datex_valid_period", period_key,
                        "validPeriod", "DATEX_UNQUALIFIED_VALID_PERIOD", "warning",
                        period.get("xml_namespace_status"),
                        "validPeriod is present without the DATEX Common XML namespace.",
                        collected_at,
                    )
                connection.execute(
                    """INSERT INTO datex_rate_valid_periods VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(datex_valid_period_key) DO UPDATE SET
                       xml_namespace_status=excluded.xml_namespace_status,
                       start_time_of_period_raw=excluded.start_time_of_period_raw,
                       end_time_of_period_raw=excluded.end_time_of_period_raw,
                       applicable_day_raw=excluded.applicable_day_raw,
                       applicable_day_canonical=excluded.applicable_day_canonical,
                       current_revision_id=excluded.current_revision_id""",
                    (period_key, rate_key, period.get("period_ordinal"), period.get("xml_namespace_status"),
                     period.get("start_time_of_period"), period.get("end_time_of_period"),
                     period.get("applicable_day"), _canonical_status(period.get("applicable_day")),
                     period_revision))
                for index, name in enumerate(period.get("period_names") or []):
                    connection.execute("INSERT OR REPLACE INTO datex_rate_period_names VALUES (?, ?, ?, ?)",
                                       (period_key, index, name.get("language"), name.get("text")))
            policy = rate.get("pricing_policy")
            if policy is not None:
                policy_key = _required_identity("datex-pricing-policy", rate_key, 0)
                policy_revision = _revision(connection, source_id, "datex_pricing_policy", policy_key,
                                             policy, None, collected_at, run_id)
                connection.execute(
                    """INSERT INTO datex_energy_pricing_policies VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(datex_pricing_policy_key) DO UPDATE SET
                       pricing_policy_raw=excluded.pricing_policy_raw,
                       pricing_policy_canonical=excluded.pricing_policy_canonical,
                       current_revision_id=excluded.current_revision_id""",
                    (policy_key, rate_key, policy.get("pricing_policy"),
                     _canonical_status(policy.get("pricing_policy")), policy_revision))
                for index, information in enumerate(policy.get("additional_information") or []):
                    connection.execute("INSERT OR REPLACE INTO datex_pricing_additional_information VALUES (?, ?, ?, ?)",
                                       (policy_key, index, information.get("language"), information.get("text")))


def save_datex_dynamic_publication(parsed, payload_bytes, database_path=DATABASE_PATH,
                                   collected_at=None, collection_run_id=None,
                                   http_status=200):
    create_database(database_path)
    collected_at = collected_at or _now()
    connection = connect_database(database_path)
    try:
        with connection:
            endpoint = _source_and_endpoint(connection, "VIA_LIETUVA_DATEX", "datex_energy_infrastructure_status")
            run_id = _start_run(connection, endpoint, collected_at, collection_run_id)
            payload_id, payload_hash = _save_raw_payload(connection, run_id, payload_bytes,
                                                         collected_at, "application/xml")
            publication_id = connection.execute(
                """INSERT INTO datex_dynamic_publications (
                   collection_run_id, publication_type, language, model_base_version,
                   schema_location, feed_description, publication_time_raw,
                   publication_time_utc, publication_creator_country,
                   publication_creator_national_identifier, table_reference, raw_payload_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, parsed.get("publication_type"), parsed.get("language"), parsed.get("model_base_version"),
                 parsed.get("schema_location"), parsed.get("feed_description"), parsed.get("publication_time"),
                 _utc_text(parsed.get("publication_time")), parsed.get("publication_creator_country"),
                 parsed.get("publication_creator_national_identifier"), parsed.get("table_reference"), payload_id),
            ).lastrowid
            counts = {"sites": 0, "stations": 0, "statuses": 0, "unmatched_stations": 0}
            for site in parsed.get("site_statuses") or []:
                matched_site = connection.execute(
                    "SELECT datex_site_key FROM datex_energy_infrastructure_sites WHERE source_site_id=? AND is_current=1",
                    (site.get("id"),)).fetchone()
                age, quality = _quality_for_timestamp(site.get("last_updated"), collected_at)
                site_observation = connection.execute(
                    """INSERT INTO datex_site_status_observations (
                       datex_dynamic_publication_id, source_site_id, source_version,
                       matched_datex_site_key, source_last_updated_raw,
                       source_last_updated_utc, observed_at, source_timestamp_age_seconds,
                       source_timestamp_quality) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (publication_id, site.get("id"), site.get("version"),
                     matched_site[0] if matched_site else None, site.get("last_updated"),
                     _utc_text(site.get("last_updated")), collected_at, age, quality),
                ).lastrowid
                counts["sites"] += 1
                for station in site.get("station_statuses") or []:
                    matched_station = connection.execute(
                        "SELECT datex_station_key FROM datex_energy_infrastructure_stations WHERE source_station_id=? AND is_current=1",
                        (station.get("id"),)).fetchone()
                    if matched_station is None:
                        counts["unmatched_stations"] += 1
                        _quality_issue(
                            connection, run_id, "datex_dynamic_station",
                            station.get("id"), "source_station_id",
                            "DATEX_DYNAMIC_WITHOUT_STATIC", "warning",
                            station.get("id"),
                            "Dynamic station has no current matching static station.",
                            collected_at,
                        )
                    station_observation = connection.execute(
                        """INSERT INTO datex_station_status_observations (
                           datex_site_status_observation_id, source_station_id, source_version,
                           matched_datex_station_key, is_available_raw, is_available_boolean)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (site_observation, station.get("id"), station.get("version"),
                         matched_station[0] if matched_station else None, station.get("is_available"),
                         1 if str(station.get("is_available")).lower() == "true" else 0 if station.get("is_available") is not None else None),
                    ).lastrowid
                    counts["stations"] += 1
                    status_ids = []
                    for status in station.get("refill_point_statuses") or []:
                        status_id = connection.execute(
                            """INSERT INTO datex_refill_point_status_observations (
                               datex_station_status_observation_id, source_status_id,
                               connector_index_raw, connector_index_integer,
                               status_raw, status_canonical) VALUES (?, ?, ?, ?, ?, ?)""",
                            (station_observation, status.get("id"), status.get("connector_index"),
                             _integer(status.get("connector_index")), status.get("status") or "UNKNOWN",
                             _canonical_status(status.get("status"))),
                        ).lastrowid
                        status_ids.append(status_id)
                        counts["statuses"] += 1
                    _map_dynamic_statuses(connection, matched_station[0] if matched_station else None,
                                          status_ids)
                    if matched_station is not None and status_ids:
                        refill_count = connection.execute(
                            "SELECT COUNT(*) FROM datex_refill_points WHERE datex_station_key=? AND is_current=1",
                            (matched_station[0],),
                        ).fetchone()[0]
                        connector_count = connection.execute(
                            """SELECT COUNT(*) FROM datex_connectors
                               JOIN datex_refill_points USING (datex_refill_point_key)
                               WHERE datex_refill_points.datex_station_key=?
                                 AND datex_connectors.is_current=1""",
                            (matched_station[0],),
                        ).fetchone()[0]
                        if len(status_ids) not in (refill_count, connector_count):
                            _quality_issue(
                                connection, run_id, "datex_dynamic_station",
                                station.get("id"), "refillPointStatus",
                                "DATEX_STATUS_COUNT_MISMATCH", "warning",
                                len(status_ids),
                                f"Dynamic status count {len(status_ids)} differs from "
                                f"static refill point count {refill_count} and connector count {connector_count}.",
                                collected_at,
                            )
            _finish_run(connection, run_id, collected_at=collected_at,
                        records=counts["stations"], payload_hash=payload_hash,
                        publication_time=parsed.get("publication_time"), http_status=http_status)
        return {"collection_run_id": run_id, **counts}
    finally:
        connection.close()


def _map_dynamic_statuses(connection, station_key, status_observation_ids):
    if station_key is None or not status_observation_ids:
        return
    refill_rows = connection.execute(
        "SELECT datex_refill_point_key FROM datex_refill_points WHERE datex_station_key=? AND is_current=1 ORDER BY ordinal_within_station",
        (station_key,)).fetchall()
    connector_rows = connection.execute(
        """SELECT datex_connectors.datex_connector_key FROM datex_connectors
           JOIN datex_refill_points USING (datex_refill_point_key)
           WHERE datex_refill_points.datex_station_key=? AND datex_connectors.is_current=1
           ORDER BY datex_refill_points.ordinal_within_station, datex_connectors.connector_ordinal""",
        (station_key,)).fetchall()
    if len(status_observation_ids) == len(connector_rows):
        for status_id, connector in zip(status_observation_ids, connector_rows):
            connection.execute(
                "INSERT INTO datex_dynamic_status_static_mappings VALUES (?, NULL, ?, 'equal_connector_count_and_ordinal', 0.70, ?)",
                (status_id, connector[0], _json({"status_count": len(status_observation_ids), "connector_count": len(connector_rows)})))
    elif len(status_observation_ids) == len(refill_rows):
        for status_id, refill in zip(status_observation_ids, refill_rows):
            connection.execute(
                "INSERT INTO datex_dynamic_status_static_mappings VALUES (?, ?, NULL, 'equal_refill_point_count_and_ordinal', 0.65, ?)",
                (status_id, refill[0], _json({"status_count": len(status_observation_ids), "refill_point_count": len(refill_rows)})))


def refresh_cross_source_mappings(connection, observed_at):
    """Create conservative site and equipment links with explicit evidence."""
    ocpi_rows = connection.execute(
        "SELECT * FROM ocpi_locations WHERE is_current=1").fetchall()
    for ocpi in ocpi_rows:
        canonical_site_id = f"charging-site:{_hash_text(ocpi['ocpi_location_key'])[:24]}"
        connection.execute(
            """INSERT OR IGNORE INTO charging_sites VALUES (?, ?, ?, ?, 'candidate', ?)""",
            (canonical_site_id, ocpi["name"], ocpi["latitude"], ocpi["longitude"], observed_at))
        _ensure_site_link(connection, canonical_site_id, "OCPI", "OCPI_LOCATION",
                          ocpi["ocpi_location_key"], "same_physical_site",
                          "source_identity", 1.0, {"source_identity": True}, observed_at)
        station_identifier = f"EGI-ST-{ocpi['source_location_id']}"
        datex = connection.execute(
            "SELECT * FROM datex_energy_infrastructure_stations WHERE source_station_id=? AND is_current=1",
            (station_identifier,)).fetchone()
        if datex:
            distance = _distance_approximate_meters(
                ocpi["latitude"], ocpi["longitude"], datex["latitude"], datex["longitude"])
            confidence = 0.98 if distance is not None and distance <= 100 else 0.85
            _ensure_site_link(connection, canonical_site_id, "DATEX_II", "DATEX_STATION",
                              datex["datex_station_key"], "same_physical_site",
                              "matching_numeric_identifier_and_coordinates", confidence,
                              {"ocpi_source_location_id": ocpi["source_location_id"],
                               "datex_source_station_id": datex["source_station_id"],
                               "coordinate_distance_meters": distance}, observed_at)
    for datex in connection.execute(
        "SELECT * FROM datex_energy_infrastructure_stations WHERE is_current=1"):
        linked = connection.execute(
            """SELECT 1 FROM charging_site_source_links WHERE source_system='DATEX_II'
               AND source_entity_type='DATEX_STATION' AND source_entity_key=? AND is_current=1""",
            (datex["datex_station_key"],)).fetchone()
        if not linked:
            canonical_site_id = f"charging-site:{_hash_text(datex['datex_station_key'])[:24]}"
            connection.execute(
                "INSERT OR IGNORE INTO charging_sites VALUES (?, NULL, ?, ?, 'candidate', ?)",
                (canonical_site_id, datex["latitude"], datex["longitude"], observed_at))
            _ensure_site_link(connection, canonical_site_id, "DATEX_II", "DATEX_STATION",
                              datex["datex_station_key"], "same_physical_site",
                              "source_identity", 1.0, {"source_identity": True}, observed_at)
    _refresh_equipment_links(connection, observed_at)


def _ensure_site_link(connection, site_id, system, entity_type, entity_key,
                      relation, method, confidence, evidence, observed_at):
    connection.execute(
        """UPDATE charging_site_source_links
           SET is_current=0, valid_to=?
           WHERE source_system=? AND source_entity_type=? AND source_entity_key=?
             AND charging_site_id<>? AND is_current=1 AND manually_verified=0
             AND confidence_score<=?""",
        (observed_at, system, entity_type, entity_key, site_id, confidence),
    )
    exists = connection.execute(
        """SELECT 1 FROM charging_site_source_links WHERE source_system=?
           AND source_entity_type=? AND source_entity_key=? AND charging_site_id=? AND is_current=1""",
        (system, entity_type, entity_key, site_id)).fetchone()
    if not exists:
        connection.execute(
            """INSERT INTO charging_site_source_links (
               charging_site_id, source_system, source_entity_type, source_entity_key,
               relation_type, mapping_method, mapping_algorithm_version,
               confidence_score, mapping_evidence_json, valid_from)
               VALUES (?, ?, ?, ?, ?, ?, '1.0.0', ?, ?, ?)""",
            (site_id, system, entity_type, entity_key, relation, method,
             confidence, _json(evidence), observed_at))


def _refresh_equipment_links(connection, observed_at):
    for refill in connection.execute(
        """SELECT datex_refill_points.*, charging_site_source_links.charging_site_id
           FROM datex_refill_points
           JOIN datex_energy_infrastructure_stations USING (datex_station_key)
           JOIN charging_site_source_links ON charging_site_source_links.source_entity_key=datex_refill_points.datex_station_key
           WHERE datex_refill_points.is_current=1 AND charging_site_source_links.source_entity_type='DATEX_STATION'
             AND charging_site_source_links.is_current=1"""):
        normalized_refill = re.sub(r"^LT-", "", refill["source_refill_point_id"], flags=re.IGNORECASE)
        matches = connection.execute(
            """SELECT ocpi_evses.* FROM ocpi_evses
               JOIN ocpi_locations USING (ocpi_location_key)
               JOIN charging_site_source_links ON charging_site_source_links.source_entity_key=ocpi_locations.ocpi_location_key
               WHERE charging_site_source_links.charging_site_id=? AND charging_site_source_links.is_current=1
                 AND ocpi_evses.is_current=1 AND (ocpi_evses.public_evse_id=? OR ocpi_evses.public_evse_id LIKE ?)""",
            (refill["charging_site_id"], normalized_refill, normalized_refill + "-%"),
        ).fetchall()
        if not matches:
            continue
        equipment_id = f"charging-equipment:{_hash_text(refill['datex_refill_point_key'])[:24]}"
        connection.execute("INSERT OR IGNORE INTO charging_equipment VALUES (?, ?, 'refill_point_group', ?)",
                           (equipment_id, refill["charging_site_id"], observed_at))
        _ensure_equipment_link(connection, equipment_id, "DATEX_II", "DATEX_REFILL_POINT",
                               refill["datex_refill_point_key"], "represents_group", "one_to_many",
                               "normalized_public_identifier", 0.95,
                               {"normalized_refill_point_id": normalized_refill}, observed_at)
        for evse in matches:
            _ensure_equipment_link(connection, equipment_id, "OCPI", "OCPI_EVSE",
                                   evse["ocpi_evse_key"], "member_of", "many_to_one",
                                   "normalized_public_identifier_prefix", 0.95,
                                   {"datex_refill_point_id": refill["source_refill_point_id"],
                                    "ocpi_public_evse_id": evse["public_evse_id"]}, observed_at)


def _ensure_equipment_link(connection, equipment_id, system, entity_type,
                           entity_key, relation, cardinality, method,
                           confidence, evidence, observed_at):
    exists = connection.execute(
        """SELECT 1 FROM charging_equipment_source_links WHERE charging_equipment_id=?
           AND source_system=? AND source_entity_type=? AND source_entity_key=? AND is_current=1""",
        (equipment_id, system, entity_type, entity_key)).fetchone()
    if not exists:
        connection.execute(
            """INSERT INTO charging_equipment_source_links (
               charging_equipment_id, source_system, source_entity_type,
               source_entity_key, relation_type, mapping_cardinality,
               mapping_method, mapping_algorithm_version, confidence_score,
               mapping_evidence_json, valid_from)
               VALUES (?, ?, ?, ?, ?, ?, ?, '1.0.0', ?, ?, ?)""",
            (equipment_id, system, entity_type, entity_key, relation, cardinality,
             method, confidence, _json(evidence), observed_at))


def _distance_approximate_meters(latitude_a, longitude_a, latitude_b, longitude_b):
    if None in (latitude_a, longitude_a, latitude_b, longitude_b):
        return None
    latitude_scale = 111_320.0
    longitude_scale = 111_320.0 * max(0.1, __import__("math").cos(
        __import__("math").radians((latitude_a + latitude_b) / 2)))
    squared_distance = (
        ((latitude_a - latitude_b) * latitude_scale) ** 2
        + ((longitude_a - longitude_b) * longitude_scale) ** 2
    )
    return squared_distance ** 0.5
