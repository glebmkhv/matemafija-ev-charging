"""Create and open the project's SQLite database."""

from pathlib import Path
import sqlite3


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


if __name__ == "__main__":
    create_database()
    print(f"Database ready: {DATABASE_PATH}")