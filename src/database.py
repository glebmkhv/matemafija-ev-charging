"""Create the SQLite database and persist normalized OCPI observations."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "ev_charging.db"
SCHEMA_PATH = PROJECT_ROOT / "src" / "schema.sql"


LOCATION_MIGRATION_COLUMNS = {
    "source_country_code": "TEXT",
    "source_party_id": "TEXT",
    "source_location_id": "TEXT",
    "publish": "INTEGER",
    "country": "TEXT",
    "parking_type": "TEXT",
    "time_zone": "TEXT",
    "charging_when_closed": "INTEGER",
    "operator_website": "TEXT",
    "owner_name": "TEXT",
    "owner_website": "TEXT",
    "help_phone": "TEXT",
    "help_email": "TEXT",
    "facilities_json": "TEXT",
    "directions_json": "TEXT",
    "parking_places_json": "TEXT",
    "images_json": "TEXT",
    "opening_times_json": "TEXT",
    "energy_mix_json": "TEXT",
    "raw_json": "TEXT NOT NULL DEFAULT '{}'",
}

EVSE_MIGRATION_COLUMNS = {
    "source_uid": "TEXT",
    "public_evse_id": "TEXT",
    "physical_reference": "TEXT",
    "capabilities_json": "TEXT",
    "parking_restrictions_json": "TEXT",
    "parking_json": "TEXT",
    "raw_json": "TEXT NOT NULL DEFAULT '{}'",
}


def _json(value):
    """Serialize source data deterministically without losing Unicode."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_hash(raw_json):
    """Return a stable fingerprint for change detection."""
    return sha256(raw_json.encode("utf-8")).hexdigest()


def connect_database(database_path=DATABASE_PATH):
    """Open a connection with foreign-key checks enabled."""
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _add_missing_columns(connection, table_name, columns):
    """Add new nullable/defaulted columns to an existing local database."""
    current_columns = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }
    for column_name, column_type in columns.items():
        if column_name not in current_columns:
            connection.execute(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN {column_name} {column_type}"
            )


def _clear_legacy_connector_summary(connection):
    """Remove values from obsolete single-connector summary columns."""
    evse_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(evses)")
    }
    legacy_columns = {
        "max_power_kw",
        "connector_standard",
        "power_type",
    }
    if legacy_columns.issubset(evse_columns):
        connection.execute(
            """
            UPDATE evses
            SET max_power_kw = NULL,
                connector_standard = NULL,
                power_type = NULL
            WHERE max_power_kw IS NOT NULL
               OR connector_standard IS NOT NULL
               OR power_type IS NOT NULL
            """
        )


def create_database(database_path=DATABASE_PATH):
    """Create the schema and migrate the project's earlier MVP tables."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = connect_database(database_path)

    try:
        connection.executescript(schema)
        _add_missing_columns(
            connection,
            "locations",
            LOCATION_MIGRATION_COLUMNS,
        )
        _add_missing_columns(
            connection,
            "evses",
            EVSE_MIGRATION_COLUMNS,
        )
        _clear_legacy_connector_summary(connection)
        connection.commit()
    finally:
        connection.close()


def _source_key(*parts):
    """Join OCPI identity fields into one unambiguous database key."""
    return ":".join(str(part or "UNKNOWN") for part in parts)


def _location_key(location):
    return _source_key(
        location.get("country_code"),
        location.get("party_id"),
        location.get("id"),
    )


def _evse_key(location, evse):
    source_id = evse.get("evse_id") or evse.get("uid")
    return _source_key(
        location.get("country_code"),
        location.get("party_id"),
        source_id,
    )


def _connector_key(location, evse, connector, connector_index):
    source_id = connector.get("id")
    if source_id is None:
        source_id = f"INDEX-{connector_index}"
    return _source_key(_evse_key(location, evse), source_id)


def _tariff_key(country_code, party_id, tariff_id):
    return _source_key(country_code, party_id, tariff_id)


def _record_change(
    connection,
    entity_type,
    entity_id,
    source_object,
    observed_at,
    source_last_updated,
    collector_run_id,
):
    """Append a source version only when its content has not been seen before."""
    raw_json = _json(source_object)
    connection.execute(
        """
        INSERT OR IGNORE INTO entity_changes (
            entity_type, entity_id, observed_at, source_last_updated,
            content_hash, raw_json, collector_run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_type,
            entity_id,
            observed_at,
            source_last_updated,
            _content_hash(raw_json),
            raw_json,
            collector_run_id,
        ),
    )


def _save_location(
    connection,
    location,
    collected_at,
    collector_run_id,
):
    location_id = _location_key(location)
    coordinates = location.get("coordinates") or {}
    operator = location.get("operator") or {}
    owner = location.get("owner") or {}
    location_without_evses = {
        key: value
        for key, value in location.items()
        if key != "evses"
    }
    raw_json = _json(location_without_evses)

    connection.execute(
        """
        INSERT INTO locations (
            location_id, source_country_code, source_party_id,
            source_location_id, publish, name, address, city, country,
            latitude, longitude, parking_type, time_zone,
            charging_when_closed, operator_name, operator_website,
            owner_name, owner_website, help_phone, help_email,
            facilities_json, directions_json, parking_places_json,
            images_json, opening_times_json, energy_mix_json, raw_json,
            source_last_updated, first_seen_at, last_seen_at
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(location_id) DO UPDATE SET
            source_country_code = excluded.source_country_code,
            source_party_id = excluded.source_party_id,
            source_location_id = excluded.source_location_id,
            publish = excluded.publish,
            name = excluded.name,
            address = excluded.address,
            city = excluded.city,
            country = excluded.country,
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            parking_type = excluded.parking_type,
            time_zone = excluded.time_zone,
            charging_when_closed = excluded.charging_when_closed,
            operator_name = excluded.operator_name,
            operator_website = excluded.operator_website,
            owner_name = excluded.owner_name,
            owner_website = excluded.owner_website,
            help_phone = excluded.help_phone,
            help_email = excluded.help_email,
            facilities_json = excluded.facilities_json,
            directions_json = excluded.directions_json,
            parking_places_json = excluded.parking_places_json,
            images_json = excluded.images_json,
            opening_times_json = excluded.opening_times_json,
            energy_mix_json = excluded.energy_mix_json,
            raw_json = excluded.raw_json,
            source_last_updated = excluded.source_last_updated,
            last_seen_at = excluded.last_seen_at
        """,
        (
            location_id,
            location.get("country_code"),
            location.get("party_id"),
            str(location.get("id")) if location.get("id") is not None else None,
            location.get("publish"),
            location.get("name"),
            location.get("address"),
            location.get("city"),
            location.get("country"),
            coordinates.get("latitude"),
            coordinates.get("longitude"),
            location.get("parking_type"),
            location.get("time_zone"),
            location.get("charging_when_closed"),
            operator.get("name"),
            operator.get("website"),
            owner.get("name"),
            owner.get("website"),
            location.get("help_phone"),
            location.get("help_email"),
            _json(location.get("facilities") or []),
            _json(location.get("directions") or []),
            _json(location.get("parking_places") or []),
            _json(location.get("images") or []),
            _json(location.get("opening_times")),
            _json(location.get("energy_mix")),
            raw_json,
            location.get("last_updated"),
            collected_at,
            collected_at,
        ),
    )
    _record_change(
        connection,
        "location",
        location_id,
        location_without_evses,
        collected_at,
        location.get("last_updated"),
        collector_run_id,
    )
    return location_id


def _save_evse(
    connection,
    location,
    location_id,
    evse,
    collected_at,
    collector_run_id,
):
    evse_id = _evse_key(location, evse)
    evse_without_connectors = {
        key: value
        for key, value in evse.items()
        if key != "connectors"
    }
    raw_json = _json(evse_without_connectors)
    status = evse.get("status") or "UNKNOWN"

    connection.execute(
        """
        INSERT INTO evses (
            evse_id, location_id, source_uid, public_evse_id,
            current_status, physical_reference, capabilities_json,
            parking_restrictions_json, parking_json, raw_json,
            source_last_updated, first_seen_at, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(evse_id) DO UPDATE SET
            location_id = excluded.location_id,
            source_uid = excluded.source_uid,
            public_evse_id = excluded.public_evse_id,
            current_status = excluded.current_status,
            physical_reference = excluded.physical_reference,
            capabilities_json = excluded.capabilities_json,
            parking_restrictions_json = excluded.parking_restrictions_json,
            parking_json = excluded.parking_json,
            raw_json = excluded.raw_json,
            source_last_updated = excluded.source_last_updated,
            last_seen_at = excluded.last_seen_at
        """,
        (
            evse_id,
            location_id,
            str(evse.get("uid")) if evse.get("uid") is not None else None,
            evse.get("evse_id"),
            status,
            evse.get("physical_reference"),
            _json(evse.get("capabilities") or []),
            _json(evse.get("parking_restrictions") or []),
            _json(evse.get("parking") or []),
            raw_json,
            evse.get("last_updated"),
            collected_at,
            collected_at,
        ),
    )

    _record_change(
        connection,
        "evse",
        evse_id,
        evse_without_connectors,
        collected_at,
        evse.get("last_updated"),
        collector_run_id,
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO status_history (
            collected_at, evse_id, status, source_last_updated,
            location_id, collector_run_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            collected_at,
            evse_id,
            status,
            evse.get("last_updated"),
            location_id,
            collector_run_id,
        ),
    )
    return evse_id


def _save_connector(
    connection,
    location,
    evse,
    evse_id,
    connector,
    connector_index,
    collected_at,
    collector_run_id,
):
    connector_id = _connector_key(
        location,
        evse,
        connector,
        connector_index,
    )
    raw_json = _json(connector)

    connection.execute(
        """
        INSERT INTO connectors (
            connector_id, evse_id, source_connector_id, standard, format,
            power_type, voltage, amperage, max_electric_power_w,
            terms_and_conditions, capabilities_json, raw_json,
            source_last_updated, first_seen_at, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(connector_id) DO UPDATE SET
            evse_id = excluded.evse_id,
            source_connector_id = excluded.source_connector_id,
            standard = excluded.standard,
            format = excluded.format,
            power_type = excluded.power_type,
            voltage = excluded.voltage,
            amperage = excluded.amperage,
            max_electric_power_w = excluded.max_electric_power_w,
            terms_and_conditions = excluded.terms_and_conditions,
            capabilities_json = excluded.capabilities_json,
            raw_json = excluded.raw_json,
            source_last_updated = excluded.source_last_updated,
            last_seen_at = excluded.last_seen_at
        """,
        (
            connector_id,
            evse_id,
            str(connector.get("id") or f"INDEX-{connector_index}"),
            connector.get("standard"),
            connector.get("format"),
            connector.get("power_type"),
            connector.get("voltage"),
            connector.get("amperage"),
            connector.get("max_electric_power"),
            connector.get("terms_and_conditions"),
            _json(connector.get("capabilities") or []),
            raw_json,
            connector.get("last_updated"),
            collected_at,
            collected_at,
        ),
    )

    connection.execute(
        "DELETE FROM connector_tariffs WHERE connector_id = ?",
        (connector_id,),
    )
    for source_tariff_id in connector.get("tariff_ids") or []:
        tariff_id = _tariff_key(
            location.get("country_code"),
            location.get("party_id"),
            source_tariff_id,
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO connector_tariffs (connector_id, tariff_id)
            VALUES (?, ?)
            """,
            (connector_id, tariff_id),
        )

    _record_change(
        connection,
        "connector",
        connector_id,
        connector,
        collected_at,
        connector.get("last_updated"),
        collector_run_id,
    )


def _save_tariff(
    connection,
    tariff,
    collected_at,
    collector_run_id,
):
    tariff_id = _tariff_key(
        tariff.get("country_code"),
        tariff.get("party_id"),
        tariff.get("id"),
    )
    raw_json = _json(tariff)

    connection.execute(
        """
        INSERT INTO tariffs (
            tariff_id, source_country_code, source_party_id,
            source_tariff_id, name, currency, tariff_alt_url,
            min_price_json, max_price_json, start_date_time,
            end_date_time, tax_included, raw_json, source_last_updated,
            first_seen_at, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tariff_id) DO UPDATE SET
            source_country_code = excluded.source_country_code,
            source_party_id = excluded.source_party_id,
            source_tariff_id = excluded.source_tariff_id,
            name = excluded.name,
            currency = excluded.currency,
            tariff_alt_url = excluded.tariff_alt_url,
            min_price_json = excluded.min_price_json,
            max_price_json = excluded.max_price_json,
            start_date_time = excluded.start_date_time,
            end_date_time = excluded.end_date_time,
            tax_included = excluded.tax_included,
            raw_json = excluded.raw_json,
            source_last_updated = excluded.source_last_updated,
            last_seen_at = excluded.last_seen_at
        """,
        (
            tariff_id,
            tariff.get("country_code"),
            tariff.get("party_id"),
            str(tariff.get("id")) if tariff.get("id") is not None else None,
            tariff.get("name"),
            tariff.get("currency"),
            tariff.get("tariff_alt_url"),
            _json(tariff.get("min_price")),
            _json(tariff.get("max_price")),
            tariff.get("start_date_time"),
            tariff.get("end_date_time"),
            tariff.get("tax_included"),
            raw_json,
            tariff.get("last_updated"),
            collected_at,
            collected_at,
        ),
    )

    connection.execute(
        "DELETE FROM tariff_alt_texts WHERE tariff_id = ?",
        (tariff_id,),
    )
    connection.execute(
        "DELETE FROM tariff_elements WHERE tariff_id = ?",
        (tariff_id,),
    )

    for alt_text in tariff.get("tariff_alt_text") or []:
        connection.execute(
            """
            INSERT OR IGNORE INTO tariff_alt_texts (tariff_id, language, text)
            VALUES (?, ?, ?)
            """,
            (
                tariff_id,
                alt_text.get("language") or "UNKNOWN",
                alt_text.get("text") or "",
            ),
        )

    for element_index, element in enumerate(tariff.get("elements") or []):
        connection.execute(
            """
            INSERT INTO tariff_elements (tariff_id, element_index)
            VALUES (?, ?)
            """,
            (tariff_id, element_index),
        )

        for component_index, component in enumerate(
            element.get("price_components") or []
        ):
            connection.execute(
                """
                INSERT INTO tariff_price_components (
                    tariff_id, element_index, component_index,
                    component_type, price, step_size, vat
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tariff_id,
                    element_index,
                    component_index,
                    component.get("type") or "UNKNOWN",
                    str(component.get("price") or "0"),
                    component.get("step_size") or 1,
                    component.get("vat"),
                ),
            )

        restrictions = element.get("restrictions")
        if restrictions:
            connection.execute(
                """
                INSERT INTO tariff_restrictions (
                    tariff_id, element_index, start_time, end_time,
                    start_date, end_date, min_kwh, max_kwh,
                    min_power, max_power, min_duration, max_duration,
                    day_of_week_json, reservation, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tariff_id,
                    element_index,
                    restrictions.get("start_time"),
                    restrictions.get("end_time"),
                    restrictions.get("start_date"),
                    restrictions.get("end_date"),
                    restrictions.get("min_kwh"),
                    restrictions.get("max_kwh"),
                    restrictions.get("min_power"),
                    restrictions.get("max_power"),
                    restrictions.get("min_duration"),
                    restrictions.get("max_duration"),
                    _json(restrictions.get("day_of_week") or []),
                    restrictions.get("reservation"),
                    _json(restrictions),
                ),
            )

    _record_change(
        connection,
        "tariff",
        tariff_id,
        tariff,
        collected_at,
        tariff.get("last_updated"),
        collector_run_id,
    )


def save_ocpi_snapshot(
    locations,
    tariffs=None,
    database_path=DATABASE_PATH,
    collected_at=None,
    collector_run_id=None,
):
    """Save current source state, observations, and content changes atomically."""
    create_database(database_path)
    collected_at = collected_at or datetime.now(timezone.utc).isoformat()
    collector_run_id = collector_run_id or str(uuid4())
    connection = connect_database(database_path)

    counts = {
        "locations": 0,
        "evses": 0,
        "connectors": 0,
        "history_rows": 0,
        "tariffs": 0,
    }
    seen_locations = set()
    seen_evses = set()
    seen_connectors = set()

    try:
        with connection:
            for location in locations:
                location_id = _location_key(location)
                if location_id not in seen_locations:
                    _save_location(
                        connection,
                        location,
                        collected_at,
                        collector_run_id,
                    )
                    seen_locations.add(location_id)
                    counts["locations"] += 1

                for evse in location.get("evses") or []:
                    evse_id = _evse_key(location, evse)
                    if evse_id in seen_evses:
                        continue

                    _save_evse(
                        connection,
                        location,
                        location_id,
                        evse,
                        collected_at,
                        collector_run_id,
                    )
                    seen_evses.add(evse_id)
                    counts["evses"] += 1
                    counts["history_rows"] += 1

                    for connector_index, connector in enumerate(
                        evse.get("connectors") or []
                    ):
                        connector_id = _connector_key(
                            location,
                            evse,
                            connector,
                            connector_index,
                        )
                        if connector_id in seen_connectors:
                            continue
                        _save_connector(
                            connection,
                            location,
                            evse,
                            evse_id,
                            connector,
                            connector_index,
                            collected_at,
                            collector_run_id,
                        )
                        seen_connectors.add(connector_id)
                        counts["connectors"] += 1

            for tariff in tariffs or []:
                _save_tariff(
                    connection,
                    tariff,
                    collected_at,
                    collector_run_id,
                )
                counts["tariffs"] += 1
    finally:
        connection.close()

    return {
        "collector_run_id": collector_run_id,
        "collected_at": collected_at,
        **counts,
    }


if __name__ == "__main__":
    create_database()
    print(f"Database ready: {DATABASE_PATH}")
