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


class SnapshotTest(unittest.TestCase):
    def test_snapshot_upserts_current_state_and_appends_history(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.db"
            create_database(database_path)

            save_ocpi_snapshot(
                [SAMPLE_LOCATION],
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
            connection.close()

            self.assertEqual(current_status, "CHARGING")
            self.assertEqual(history, [("AVAILABLE",), ("CHARGING",)])


if __name__ == "__main__":
    unittest.main()
