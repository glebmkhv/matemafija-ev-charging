"""Create and open the project's SQLite database."""

from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "ev_charging.db"
SCHEMA_PATH = PROJECT_ROOT / "src" / "schema.sql"


def connect_database(database_path=DATABASE_PATH):
    """Open a connection with foreign-key checks enabled."""
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def create_database(database_path=DATABASE_PATH):
    """Create the tables and indexes defined in schema.sql."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = connect_database(database_path)

    try:
        connection.executescript(schema)
        connection.commit()
    finally:
        connection.close()


def _location_key(location):
    """Return a stable key that also identifies the OCPI data provider."""
    return ":".join(
        str(location.get(field) or "UNKNOWN")
        for field in ("country_code", "party_id", "id")
    )


def _evse_key(location, evse):
    """Return a stable EVSE key within its OCPI provider."""
    source_id = evse.get("evse_id") or evse.get("uid") or "UNKNOWN"
    return ":".join(
        [
            str(location.get("country_code") or "UNKNOWN"),
            str(location.get("party_id") or "UNKNOWN"),
            str(source_id),
        ]
    )


def _representative_connector(evse):
    """Choose the highest-power connector for the simplified MVP schema."""
    connectors = evse.get("connectors") or []
    if not connectors:
        return {}

    return max(
        connectors,
        key=lambda connector: connector.get("max_electric_power") or 0,
    )


def save_ocpi_snapshot(
    locations,
    database_path=DATABASE_PATH,
    collected_at=None,
    collector_run_id=None,
):
    """Upsert current OCPI facts and append one status-history snapshot."""
    create_database(database_path)

    collected_at = collected_at or datetime.now(timezone.utc).isoformat()
    collector_run_id = collector_run_id or str(uuid4())
    connection = connect_database(database_path)

    location_count = 0
    evse_count = 0
    history_count = 0
    seen_locations = set()
    seen_evses = set()

    try:
        with connection:
            for location in locations:
                location_id = _location_key(location)

                if location_id not in seen_locations:
                    coordinates = location.get("coordinates") or {}
                    operator = location.get("operator") or {}

                    connection.execute(
                        """
                        INSERT INTO locations (
                            location_id, name, address, city, latitude,
                            longitude, operator_name, source_last_updated,
                            first_seen_at, last_seen_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(location_id) DO UPDATE SET
                            name = excluded.name,
                            address = excluded.address,
                            city = excluded.city,
                            latitude = excluded.latitude,
                            longitude = excluded.longitude,
                            operator_name = excluded.operator_name,
                            source_last_updated = excluded.source_last_updated,
                            last_seen_at = excluded.last_seen_at
                        """,
                        (
                            location_id,
                            location.get("name"),
                            location.get("address"),
                            location.get("city"),
                            coordinates.get("latitude"),
                            coordinates.get("longitude"),
                            operator.get("name"),
                            location.get("last_updated"),
                            collected_at,
                            collected_at,
                        ),
                    )
                    seen_locations.add(location_id)
                    location_count += 1

                for evse in location.get("evses") or []:
                    evse_id = _evse_key(location, evse)
                    if evse_id in seen_evses:
                        continue

                    connector = _representative_connector(evse)
                    max_power_watts = connector.get("max_electric_power")
                    max_power_kw = (
                        max_power_watts / 1000
                        if isinstance(max_power_watts, (int, float))
                        else None
                    )
                    status = evse.get("status") or "UNKNOWN"

                    connection.execute(
                        """
                        INSERT INTO evses (
                            evse_id, location_id, current_status, max_power_kw,
                            connector_standard, power_type,
                            source_last_updated, first_seen_at, last_seen_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(evse_id) DO UPDATE SET
                            location_id = excluded.location_id,
                            current_status = excluded.current_status,
                            max_power_kw = excluded.max_power_kw,
                            connector_standard = excluded.connector_standard,
                            power_type = excluded.power_type,
                            source_last_updated = excluded.source_last_updated,
                            last_seen_at = excluded.last_seen_at
                        """,
                        (
                            evse_id,
                            location_id,
                            status,
                            max_power_kw,
                            connector.get("standard"),
                            connector.get("power_type"),
                            evse.get("last_updated"),
                            collected_at,
                            collected_at,
                        ),
                    )

                    connection.execute(
                        """
                        INSERT INTO status_history (
                            collected_at, evse_id, status,
                            source_last_updated, location_id, collector_run_id
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

                    seen_evses.add(evse_id)
                    evse_count += 1
                    history_count += 1
    finally:
        connection.close()

    return {
        "collector_run_id": collector_run_id,
        "collected_at": collected_at,
        "locations": location_count,
        "evses": evse_count,
        "history_rows": history_count,
    }


if __name__ == "__main__":
    create_database()
    print(f"Database ready: {DATABASE_PATH}")
