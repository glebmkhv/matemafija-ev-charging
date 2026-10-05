PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS locations (
    location_id TEXT PRIMARY KEY,
    name TEXT,
    address TEXT,
    city TEXT,
    latitude REAL,
    longitude REAL,
    operator_name TEXT,
    source_last_updated TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evses (
    evse_id TEXT PRIMARY KEY,
    location_id TEXT NOT NULL,
    current_status TEXT,
    max_power_kw REAL,
    connector_standard TEXT,
    power_type TEXT,
    source_last_updated TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY (location_id) REFERENCES locations(location_id)
);

CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    evse_id TEXT NOT NULL,
    status TEXT NOT NULL,
    source_last_updated TEXT,
    location_id TEXT,
    collector_run_id TEXT,
    FOREIGN KEY (evse_id) REFERENCES evses(evse_id)
);

CREATE TABLE IF NOT EXISTS simulation_scenarios (
    scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_name TEXT NOT NULL,
    location_id TEXT,
    evse_id TEXT,
    idle_minutes REAL NOT NULL CHECK (idle_minutes >= 0),
    queue_length INTEGER NOT NULL CHECK (queue_length >= 0),
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_status_evse_time
ON status_history(evse_id, collected_at);

CREATE INDEX IF NOT EXISTS idx_locations_city
ON locations(city);