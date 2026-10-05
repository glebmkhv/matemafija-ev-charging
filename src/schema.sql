PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS locations (
    location_id TEXT PRIMARY KEY,
    source_country_code TEXT,
    source_party_id TEXT,
    source_location_id TEXT,
    publish INTEGER,
    name TEXT,
    address TEXT,
    city TEXT,
    country TEXT,
    latitude REAL,
    longitude REAL,
    parking_type TEXT,
    time_zone TEXT,
    charging_when_closed INTEGER,
    operator_name TEXT,
    operator_website TEXT,
    owner_name TEXT,
    owner_website TEXT,
    help_phone TEXT,
    help_email TEXT,
    facilities_json TEXT,
    directions_json TEXT,
    parking_places_json TEXT,
    images_json TEXT,
    opening_times_json TEXT,
    energy_mix_json TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}',
    source_last_updated TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evses (
    evse_id TEXT PRIMARY KEY,
    location_id TEXT NOT NULL,
    source_uid TEXT,
    public_evse_id TEXT,
    current_status TEXT,
    physical_reference TEXT,
    capabilities_json TEXT,
    parking_restrictions_json TEXT,
    parking_json TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}',
    source_last_updated TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY (location_id) REFERENCES locations(location_id)
);

-- Every connector is retained; no representative connector is selected.
CREATE TABLE IF NOT EXISTS connectors (
    connector_id TEXT PRIMARY KEY,
    evse_id TEXT NOT NULL,
    source_connector_id TEXT NOT NULL,
    standard TEXT,
    format TEXT,
    power_type TEXT,
    voltage REAL,
    amperage REAL,
    max_electric_power_w REAL,
    terms_and_conditions TEXT,
    capabilities_json TEXT,
    raw_json TEXT NOT NULL,
    source_last_updated TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY (evse_id) REFERENCES evses(evse_id)
);

CREATE TABLE IF NOT EXISTS connector_tariffs (
    connector_id TEXT NOT NULL,
    tariff_id TEXT NOT NULL,
    PRIMARY KEY (connector_id, tariff_id),
    FOREIGN KEY (connector_id) REFERENCES connectors(connector_id)
);

-- A row is appended on every poll, even when the source status is unchanged.
CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    evse_id TEXT NOT NULL,
    status TEXT NOT NULL,
    source_last_updated TEXT,
    location_id TEXT NOT NULL,
    collector_run_id TEXT NOT NULL,
    FOREIGN KEY (evse_id) REFERENCES evses(evse_id),
    FOREIGN KEY (location_id) REFERENCES locations(location_id),
    UNIQUE (collector_run_id, evse_id)
);

-- A new source version is appended only when an entity's content changes.
CREATE TABLE IF NOT EXISTS entity_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_last_updated TEXT,
    content_hash TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    collector_run_id TEXT NOT NULL,
    UNIQUE (entity_type, entity_id, content_hash)
);

CREATE TABLE IF NOT EXISTS tariffs (
    tariff_id TEXT PRIMARY KEY,
    source_country_code TEXT,
    source_party_id TEXT,
    source_tariff_id TEXT,
    name TEXT,
    currency TEXT,
    tariff_alt_url TEXT,
    min_price_json TEXT,
    max_price_json TEXT,
    start_date_time TEXT,
    end_date_time TEXT,
    tax_included INTEGER,
    raw_json TEXT NOT NULL,
    source_last_updated TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tariff_alt_texts (
    tariff_id TEXT NOT NULL,
    language TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (tariff_id, language, text),
    FOREIGN KEY (tariff_id) REFERENCES tariffs(tariff_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tariff_elements (
    tariff_id TEXT NOT NULL,
    element_index INTEGER NOT NULL,
    PRIMARY KEY (tariff_id, element_index),
    FOREIGN KEY (tariff_id) REFERENCES tariffs(tariff_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tariff_price_components (
    tariff_id TEXT NOT NULL,
    element_index INTEGER NOT NULL,
    component_index INTEGER NOT NULL,
    component_type TEXT NOT NULL,
    price TEXT NOT NULL,
    step_size INTEGER NOT NULL,
    vat REAL,
    PRIMARY KEY (tariff_id, element_index, component_index),
    FOREIGN KEY (tariff_id, element_index)
        REFERENCES tariff_elements(tariff_id, element_index)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tariff_restrictions (
    tariff_id TEXT NOT NULL,
    element_index INTEGER NOT NULL,
    start_time TEXT,
    end_time TEXT,
    start_date TEXT,
    end_date TEXT,
    min_kwh REAL,
    max_kwh REAL,
    min_power REAL,
    max_power REAL,
    min_duration INTEGER,
    max_duration INTEGER,
    day_of_week_json TEXT,
    reservation TEXT,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (tariff_id, element_index),
    FOREIGN KEY (tariff_id, element_index)
        REFERENCES tariff_elements(tariff_id, element_index)
        ON DELETE CASCADE
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

CREATE INDEX IF NOT EXISTS idx_status_run
ON status_history(collector_run_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_status_run_evse_unique
ON status_history(collector_run_id, evse_id);

CREATE INDEX IF NOT EXISTS idx_entity_changes_entity_time
ON entity_changes(entity_type, entity_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_locations_city
ON locations(city);

CREATE INDEX IF NOT EXISTS idx_connectors_evse
ON connectors(evse_id);
