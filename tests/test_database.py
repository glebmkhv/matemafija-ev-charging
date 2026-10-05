import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.database import create_database, save_ocpi_snapshot


SAMPLE_LOCATION = {
    "country_code": "LT",
    "party_id": "TEST",
    "id": "1",
    "name": "Test station",
    "city": "Vilnius",
    "coordinates": {"latitude": "54.68", "longitude": "25.28"},
    "operator": {"name": "Test operator"},
    "last_updated": "2026-10-05T12:00:00",
    "evses": [
        {
            "uid": "10",
            "evse_id": "LT*TEST*E10",
            "status": "AVAILABLE",
            "last_updated": "2026-10-05T12:00:00",
            "connectors": [
                {
                    "standard": "IEC_62196_T2",
                    "power_type": "AC_3_PHASE",
                    "max_electric_power": 22000,
                }
            ],
        }
    ],
}

SAMPLE_TARIFF = {
    "country_code": "LT",
    "party_id": "TEST",
    "id": "T1",
    "currency": "EUR",
    "tariff_alt_text": [
        {"language": "en", "text": "0.30 EUR/kWh"},
    ],
    "elements": [
        {
            "price_components": [
                {
                    "type": "ENERGY",
                    "price": "0.3000",
                    "step_size": 1,
                    "vat": 21.0,
                }
            ],
            "restrictions": {
                "start_time": "08:00",
                "end_time": "18:00",
                "day_of_week": ["MONDAY"],
            },
        }
    ],
    "last_updated": "2026-10-05 12:00:00",
}


class SnapshotTest(unittest.TestCase):
    def test_snapshot_upserts_current_state_and_appends_history(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.db"
            create_database(database_path)

            save_ocpi_snapshot(
                [SAMPLE_LOCATION],
                tariffs=[SAMPLE_TARIFF],
                database_path=database_path,
                collected_at="2026-10-05T12:00:00+00:00",
                collector_run_id="run-1",
            )

            changed = dict(SAMPLE_LOCATION)
            changed["evses"] = [dict(SAMPLE_LOCATION["evses"][0])]
            changed["evses"][0]["status"] = "CHARGING"

            save_ocpi_snapshot(
                [changed],
                database_path=database_path,
                collected_at="2026-10-05T12:05:00+00:00",
                collector_run_id="run-2",
            )

            connection = sqlite3.connect(database_path)
            current_status = connection.execute(
                "SELECT current_status FROM evses"
            ).fetchone()[0]
            history = connection.execute(
                "SELECT status FROM status_history ORDER BY collected_at"
            ).fetchall()
            connector_count = connection.execute(
                "SELECT COUNT(*) FROM connectors"
            ).fetchone()[0]
            tariff_component = connection.execute(
                """
                SELECT component_type, price, vat
                FROM tariff_price_components
                """
            ).fetchone()
            change_counts = dict(
                connection.execute(
                    """
                    SELECT entity_type, COUNT(*)
                    FROM entity_changes
                    GROUP BY entity_type
                    """
                ).fetchall()
            )
            connection.close()

            self.assertEqual(current_status, "CHARGING")
            self.assertEqual(history, [("AVAILABLE",), ("CHARGING",)])
            self.assertEqual(connector_count, 1)
            self.assertEqual(tariff_component, ("ENERGY", "0.3000", 21.0))
            self.assertEqual(change_counts["location"], 1)
            self.assertEqual(change_counts["evse"], 2)
            self.assertEqual(change_counts["connector"], 1)
            self.assertEqual(change_counts["tariff"], 1)


if __name__ == "__main__":
    unittest.main()
