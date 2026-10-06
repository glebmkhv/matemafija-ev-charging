PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS data_sources (
    data_source_id INTEGER PRIMARY KEY,
    source_code TEXT NOT NULL UNIQUE,
    protocol TEXT NOT NULL,
    protocol_version TEXT,
    publisher_name TEXT,
    country_code TEXT,
    national_identifier TEXT,
    base_url TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_endpoints (
    source_endpoint_id INTEGER PRIMARY KEY,
    data_source_id INTEGER NOT NULL,
    endpoint_type TEXT NOT NULL,
    endpoint_url TEXT NOT NULL,
    expected_format TEXT NOT NULL CHECK (expected_format IN ('JSON', 'XML')),
    collection_frequency_seconds INTEGER NOT NULL CHECK (collection_frequency_seconds > 0),
    is_full_snapshot INTEGER NOT NULL CHECK (is_full_snapshot IN (0, 1)),
    contains_dynamic_data INTEGER NOT NULL CHECK (contains_dynamic_data IN (0, 1)),
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    UNIQUE (data_source_id, endpoint_type),
    FOREIGN KEY (data_source_id) REFERENCES data_sources(data_source_id)
);

CREATE TABLE IF NOT EXISTS collection_runs (
    collection_run_id TEXT PRIMARY KEY,
    source_endpoint_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    run_status TEXT NOT NULL CHECK (run_status IN ('running', 'success', 'partial', 'failed')),
    is_complete_snapshot INTEGER NOT NULL DEFAULT 0 CHECK (is_complete_snapshot IN (0, 1)),
    http_status INTEGER,
    requested_url TEXT NOT NULL,
    request_parameters_json TEXT,
    server_publication_time_raw TEXT,
    server_publication_time_utc TEXT,
    server_total_count INTEGER,
    pages_expected INTEGER,
    pages_received INTEGER NOT NULL DEFAULT 0,
    records_received INTEGER NOT NULL DEFAULT 0,
    records_accepted INTEGER NOT NULL DEFAULT 0,
    records_rejected INTEGER NOT NULL DEFAULT 0,
    payload_sha256 TEXT,
    error_type TEXT,
    error_message TEXT,
    collector_version TEXT NOT NULL,
    FOREIGN KEY (source_endpoint_id) REFERENCES source_endpoints(source_endpoint_id)
);

CREATE TABLE IF NOT EXISTS collection_pages (
    collection_page_id INTEGER PRIMARY KEY,
    collection_run_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    offset_value INTEGER,
    limit_value INTEGER,
    request_url TEXT NOT NULL,
    http_status INTEGER,
    received_at TEXT NOT NULL,
    reported_total_count INTEGER,
    record_count INTEGER NOT NULL,
    payload_sha256 TEXT NOT NULL,
    UNIQUE (collection_run_id, page_number),
    FOREIGN KEY (collection_run_id) REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS raw_payloads (
    raw_payload_id INTEGER PRIMARY KEY,
    collection_run_id TEXT NOT NULL,
    collection_page_id INTEGER,
    content_type TEXT,
    content_encoding TEXT,
    payload_sha256 TEXT NOT NULL,
    payload_bytes BLOB NOT NULL,
    retrieved_at TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    FOREIGN KEY (collection_run_id) REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE,
    FOREIGN KEY (collection_page_id) REFERENCES collection_pages(collection_page_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    data_quality_issue_id INTEGER PRIMARY KEY,
    collection_run_id TEXT NOT NULL,
    source_entity_type TEXT,
    source_entity_key TEXT,
    field_path TEXT,
    issue_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('information', 'warning', 'error')),
    raw_value TEXT,
    issue_description TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (collection_run_id) REFERENCES collection_runs(collection_run_id)
);

CREATE TABLE IF NOT EXISTS source_entity_revisions (
    source_entity_revision_id INTEGER PRIMARY KEY,
    data_source_id INTEGER NOT NULL,
    source_entity_type TEXT NOT NULL,
    source_entity_key TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    source_last_updated_raw TEXT,
    source_last_updated_utc TEXT,
    normalized_content_json TEXT NOT NULL,
    raw_content TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (data_source_id, source_entity_type, source_entity_key, content_sha256),
    FOREIGN KEY (data_source_id) REFERENCES data_sources(data_source_id)
);

CREATE TABLE IF NOT EXISTS source_entity_observations (
    source_entity_observation_id INTEGER PRIMARY KEY,
    collection_run_id TEXT NOT NULL,
    source_entity_revision_id INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE (collection_run_id, source_entity_revision_id),
    FOREIGN KEY (collection_run_id) REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE,
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

-- OCPI source-native current entities.
CREATE TABLE IF NOT EXISTS ocpi_locations (
    ocpi_location_key TEXT PRIMARY KEY,
    data_source_id INTEGER NOT NULL,
    country_code TEXT NOT NULL,
    party_id TEXT NOT NULL,
    source_location_id TEXT NOT NULL,
    publish INTEGER,
    name TEXT,
    address TEXT,
    city TEXT,
    postal_code TEXT,
    state TEXT,
    country TEXT,
    latitude_raw TEXT,
    longitude_raw TEXT,
    latitude REAL,
    longitude REAL,
    parking_type TEXT,
    time_zone TEXT,
    charging_when_closed INTEGER,
    help_phone TEXT,
    help_email TEXT,
    source_last_updated_raw TEXT,
    source_last_updated_utc TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    missing_since TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    current_revision_id INTEGER NOT NULL,
    UNIQUE (data_source_id, country_code, party_id, source_location_id),
    FOREIGN KEY (data_source_id) REFERENCES data_sources(data_source_id),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS ocpi_organizations (
    ocpi_organization_key TEXT PRIMARY KEY,
    data_source_id INTEGER NOT NULL,
    organization_name TEXT NOT NULL,
    website TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    FOREIGN KEY (data_source_id) REFERENCES data_sources(data_source_id)
);

CREATE TABLE IF NOT EXISTS ocpi_location_organization_roles (
    ocpi_location_key TEXT NOT NULL,
    ocpi_organization_key TEXT NOT NULL,
    organization_role TEXT NOT NULL CHECK (organization_role IN ('operator', 'owner', 'suboperator')),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    PRIMARY KEY (ocpi_location_key, ocpi_organization_key, organization_role, valid_from),
    FOREIGN KEY (ocpi_location_key) REFERENCES ocpi_locations(ocpi_location_key),
    FOREIGN KEY (ocpi_organization_key) REFERENCES ocpi_organizations(ocpi_organization_key)
);

CREATE TABLE IF NOT EXISTS ocpi_location_directions (
    source_entity_revision_id INTEGER NOT NULL,
    direction_index INTEGER NOT NULL,
    language TEXT,
    direction_text TEXT,
    PRIMARY KEY (source_entity_revision_id, direction_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_location_facilities (
    source_entity_revision_id INTEGER NOT NULL,
    facility_index INTEGER NOT NULL,
    facility_code TEXT,
    PRIMARY KEY (source_entity_revision_id, facility_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_location_images (
    source_entity_revision_id INTEGER NOT NULL,
    image_index INTEGER NOT NULL,
    image_url TEXT,
    thumbnail_url TEXT,
    image_category TEXT,
    media_type TEXT,
    width_pixels INTEGER,
    height_pixels INTEGER,
    PRIMARY KEY (source_entity_revision_id, image_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_location_opening_times (
    source_entity_revision_id INTEGER PRIMARY KEY,
    twenty_four_seven INTEGER,
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_location_regular_hours (
    source_entity_revision_id INTEGER NOT NULL,
    regular_hour_index INTEGER NOT NULL,
    weekday INTEGER,
    period_begin TEXT,
    period_end TEXT,
    PRIMARY KEY (source_entity_revision_id, regular_hour_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_parking_places (
    ocpi_parking_place_key TEXT PRIMARY KEY,
    ocpi_location_key TEXT NOT NULL,
    source_parking_place_id TEXT NOT NULL,
    reservation_required INTEGER,
    restricted_to_type INTEGER,
    standards TEXT,
    current_revision_id INTEGER NOT NULL,
    FOREIGN KEY (ocpi_location_key) REFERENCES ocpi_locations(ocpi_location_key),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS ocpi_parking_place_vehicle_types (
    source_entity_revision_id INTEGER NOT NULL,
    parking_place_index INTEGER NOT NULL,
    vehicle_type_index INTEGER NOT NULL,
    vehicle_type TEXT,
    PRIMARY KEY (source_entity_revision_id, parking_place_index, vehicle_type_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_location_energy_mix (
    source_entity_revision_id INTEGER NOT NULL,
    energy_source_index INTEGER NOT NULL,
    energy_source TEXT,
    percentage_decimal TEXT,
    PRIMARY KEY (source_entity_revision_id, energy_source_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_evses (
    ocpi_evse_key TEXT PRIMARY KEY,
    ocpi_location_key TEXT NOT NULL,
    source_uid TEXT NOT NULL,
    public_evse_id TEXT,
    physical_reference TEXT,
    source_status_raw TEXT,
    source_status_canonical TEXT,
    source_last_updated_raw TEXT,
    source_last_updated_utc TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    missing_since TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    current_revision_id INTEGER NOT NULL,
    FOREIGN KEY (ocpi_location_key) REFERENCES ocpi_locations(ocpi_location_key),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS ocpi_evse_capabilities (
    source_entity_revision_id INTEGER NOT NULL,
    capability_index INTEGER NOT NULL,
    capability_code TEXT,
    PRIMARY KEY (source_entity_revision_id, capability_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_evse_parking_restrictions (
    source_entity_revision_id INTEGER NOT NULL,
    parking_restriction_index INTEGER NOT NULL,
    parking_restriction_code TEXT,
    PRIMARY KEY (source_entity_revision_id, parking_restriction_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_evse_parking_assignments (
    source_entity_revision_id INTEGER NOT NULL,
    parking_assignment_index INTEGER NOT NULL,
    source_parking_place_id TEXT,
    evse_position TEXT,
    PRIMARY KEY (source_entity_revision_id, parking_assignment_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_connectors (
    ocpi_connector_key TEXT PRIMARY KEY,
    ocpi_evse_key TEXT NOT NULL,
    source_connector_id TEXT NOT NULL,
    connector_standard TEXT,
    connector_format TEXT,
    power_type TEXT,
    voltage_v REAL,
    amperage_a REAL,
    max_electric_power_w REAL,
    terms_and_conditions_url TEXT,
    source_last_updated_raw TEXT,
    source_last_updated_utc TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    missing_since TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    current_revision_id INTEGER NOT NULL,
    FOREIGN KEY (ocpi_evse_key) REFERENCES ocpi_evses(ocpi_evse_key),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS ocpi_connector_capabilities (
    source_entity_revision_id INTEGER NOT NULL,
    capability_index INTEGER NOT NULL,
    capability_code TEXT,
    PRIMARY KEY (source_entity_revision_id, capability_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_evse_status_observations (
    ocpi_evse_status_observation_id INTEGER PRIMARY KEY,
    collection_run_id TEXT NOT NULL,
    ocpi_evse_key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_last_updated_raw TEXT,
    source_last_updated_utc TEXT,
    status_raw TEXT NOT NULL,
    status_canonical TEXT NOT NULL,
    source_timestamp_age_seconds REAL,
    source_timestamp_quality TEXT,
    UNIQUE (collection_run_id, ocpi_evse_key),
    FOREIGN KEY (collection_run_id) REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE,
    FOREIGN KEY (ocpi_evse_key) REFERENCES ocpi_evses(ocpi_evse_key)
);

CREATE TABLE IF NOT EXISTS ocpi_tariffs (
    ocpi_tariff_key TEXT PRIMARY KEY,
    data_source_id INTEGER NOT NULL,
    country_code TEXT NOT NULL,
    party_id TEXT NOT NULL,
    source_tariff_id TEXT NOT NULL,
    tariff_name TEXT,
    currency TEXT,
    tariff_alternative_url TEXT,
    minimum_price_raw TEXT,
    maximum_price_raw TEXT,
    start_date_time_raw TEXT,
    end_date_time_raw TEXT,
    tax_included_raw TEXT,
    source_last_updated_raw TEXT,
    source_last_updated_utc TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    missing_since TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    current_revision_id INTEGER NOT NULL,
    UNIQUE (data_source_id, country_code, party_id, source_tariff_id),
    FOREIGN KEY (data_source_id) REFERENCES data_sources(data_source_id),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS ocpi_tariff_alternative_texts (
    source_entity_revision_id INTEGER NOT NULL,
    alternative_text_index INTEGER NOT NULL,
    language TEXT,
    alternative_text TEXT,
    PRIMARY KEY (source_entity_revision_id, alternative_text_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_tariff_elements (
    source_entity_revision_id INTEGER NOT NULL,
    tariff_element_index INTEGER NOT NULL,
    PRIMARY KEY (source_entity_revision_id, tariff_element_index),
    FOREIGN KEY (source_entity_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_tariff_price_components (
    source_entity_revision_id INTEGER NOT NULL,
    tariff_element_index INTEGER NOT NULL,
    price_component_index INTEGER NOT NULL,
    component_type TEXT,
    price_decimal TEXT,
    step_size INTEGER,
    vat_percentage_decimal TEXT,
    PRIMARY KEY (source_entity_revision_id, tariff_element_index, price_component_index),
    FOREIGN KEY (source_entity_revision_id, tariff_element_index)
        REFERENCES ocpi_tariff_elements(source_entity_revision_id, tariff_element_index) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_tariff_restrictions (
    source_entity_revision_id INTEGER NOT NULL,
    tariff_element_index INTEGER NOT NULL,
    start_time TEXT,
    end_time TEXT,
    start_date TEXT,
    end_date TEXT,
    minimum_energy_kwh REAL,
    maximum_energy_kwh REAL,
    minimum_power_kw REAL,
    maximum_power_kw REAL,
    minimum_duration_seconds INTEGER,
    maximum_duration_seconds INTEGER,
    reservation_restriction TEXT,
    restrictions_raw_json TEXT NOT NULL,
    PRIMARY KEY (source_entity_revision_id, tariff_element_index),
    FOREIGN KEY (source_entity_revision_id, tariff_element_index)
        REFERENCES ocpi_tariff_elements(source_entity_revision_id, tariff_element_index) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_tariff_restriction_days (
    source_entity_revision_id INTEGER NOT NULL,
    tariff_element_index INTEGER NOT NULL,
    day_index INTEGER NOT NULL,
    day_of_week TEXT,
    PRIMARY KEY (source_entity_revision_id, tariff_element_index, day_index),
    FOREIGN KEY (source_entity_revision_id, tariff_element_index)
        REFERENCES ocpi_tariff_restrictions(source_entity_revision_id, tariff_element_index) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_connector_tariff_assignments (
    ocpi_connector_key TEXT NOT NULL,
    ocpi_tariff_key TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    PRIMARY KEY (ocpi_connector_key, ocpi_tariff_key, valid_from),
    FOREIGN KEY (ocpi_connector_key) REFERENCES ocpi_connectors(ocpi_connector_key)
);

-- Public OCPI discovery/credentials metadata. Authentication tokens are never stored.
CREATE TABLE IF NOT EXISTS ocpi_credentials_metadata (
    ocpi_credentials_metadata_id INTEGER PRIMARY KEY,
    collection_run_id TEXT NOT NULL UNIQUE,
    credentials_url TEXT,
    token_was_present INTEGER NOT NULL DEFAULT 0 CHECK (token_was_present IN (0, 1)),
    sanitized_raw_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    FOREIGN KEY (collection_run_id) REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ocpi_credential_roles (
    ocpi_credentials_metadata_id INTEGER NOT NULL,
    role_index INTEGER NOT NULL,
    role TEXT,
    country_code TEXT,
    party_id TEXT,
    business_name TEXT,
    business_website TEXT,
    business_logo_json TEXT,
    PRIMARY KEY (ocpi_credentials_metadata_id, role_index),
    FOREIGN KEY (ocpi_credentials_metadata_id)
        REFERENCES ocpi_credentials_metadata(ocpi_credentials_metadata_id) ON DELETE CASCADE
);

-- DATEX II static source-native entities.
CREATE TABLE IF NOT EXISTS datex_static_publications (
    datex_static_publication_id INTEGER PRIMARY KEY,
    collection_run_id TEXT NOT NULL UNIQUE,
    publication_type TEXT NOT NULL,
    language TEXT,
    model_base_version TEXT,
    schema_location TEXT,
    feed_description TEXT,
    publication_time_raw TEXT,
    publication_time_utc TEXT,
    publication_creator_country TEXT,
    publication_creator_national_identifier TEXT,
    raw_payload_id INTEGER NOT NULL,
    FOREIGN KEY (collection_run_id) REFERENCES collection_runs(collection_run_id),
    FOREIGN KEY (raw_payload_id) REFERENCES raw_payloads(raw_payload_id)
);

CREATE TABLE IF NOT EXISTS datex_energy_infrastructure_tables (
    datex_table_key TEXT PRIMARY KEY,
    data_source_id INTEGER NOT NULL,
    source_table_id TEXT NOT NULL,
    source_version TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    current_revision_id INTEGER NOT NULL,
    UNIQUE (data_source_id, source_table_id),
    FOREIGN KEY (data_source_id) REFERENCES data_sources(data_source_id),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS datex_energy_infrastructure_sites (
    datex_site_key TEXT PRIMARY KEY,
    datex_table_key TEXT,
    data_source_id INTEGER NOT NULL,
    source_site_id TEXT NOT NULL,
    source_version TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    missing_since TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    current_revision_id INTEGER,
    UNIQUE (data_source_id, source_site_id),
    FOREIGN KEY (datex_table_key) REFERENCES datex_energy_infrastructure_tables(datex_table_key),
    FOREIGN KEY (data_source_id) REFERENCES data_sources(data_source_id),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS datex_energy_infrastructure_stations (
    datex_station_key TEXT PRIMARY KEY,
    datex_site_key TEXT,
    data_source_id INTEGER NOT NULL,
    source_station_id TEXT NOT NULL,
    source_version TEXT,
    source_last_updated_raw TEXT,
    source_last_updated_utc TEXT,
    latitude_raw TEXT,
    longitude_raw TEXT,
    latitude REAL,
    longitude REAL,
    number_of_refill_points INTEGER,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    missing_since TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    current_revision_id INTEGER,
    UNIQUE (data_source_id, source_station_id),
    FOREIGN KEY (datex_site_key) REFERENCES datex_energy_infrastructure_sites(datex_site_key),
    FOREIGN KEY (data_source_id) REFERENCES data_sources(data_source_id),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS datex_organizations (
    datex_organization_key TEXT PRIMARY KEY,
    data_source_id INTEGER NOT NULL,
    organization_name TEXT,
    organization_description TEXT,
    link_to_general_information TEXT,
    telephone_number TEXT,
    source_last_updated_raw TEXT,
    source_last_updated_utc TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    current_revision_id INTEGER NOT NULL,
    FOREIGN KEY (data_source_id) REFERENCES data_sources(data_source_id),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS datex_station_organization_roles (
    datex_station_key TEXT NOT NULL,
    datex_organization_key TEXT NOT NULL,
    organization_role TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    PRIMARY KEY (datex_station_key, datex_organization_key, organization_role, valid_from),
    FOREIGN KEY (datex_station_key) REFERENCES datex_energy_infrastructure_stations(datex_station_key),
    FOREIGN KEY (datex_organization_key) REFERENCES datex_organizations(datex_organization_key)
);

CREATE TABLE IF NOT EXISTS datex_refill_points (
    datex_refill_point_key TEXT PRIMARY KEY,
    datex_station_key TEXT NOT NULL,
    data_source_id INTEGER NOT NULL,
    source_refill_point_id TEXT NOT NULL,
    source_version TEXT,
    xsi_type TEXT,
    usage_type TEXT,
    ordinal_within_station INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    missing_since TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    current_revision_id INTEGER NOT NULL,
    UNIQUE (data_source_id, source_refill_point_id),
    FOREIGN KEY (datex_station_key) REFERENCES datex_energy_infrastructure_stations(datex_station_key),
    FOREIGN KEY (data_source_id) REFERENCES data_sources(data_source_id),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS datex_connectors (
    datex_connector_key TEXT PRIMARY KEY,
    datex_refill_point_key TEXT NOT NULL,
    connector_ordinal INTEGER NOT NULL,
    connector_type_raw TEXT,
    connector_type_canonical TEXT,
    max_power_at_socket_raw TEXT,
    max_power_at_socket_kw REAL,
    unit_interpretation_status TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    missing_since TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    current_revision_id INTEGER NOT NULL,
    UNIQUE (datex_refill_point_key, connector_ordinal),
    FOREIGN KEY (datex_refill_point_key) REFERENCES datex_refill_points(datex_refill_point_key),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS datex_electric_energy_mixes (
    datex_energy_mix_key TEXT PRIMARY KEY,
    datex_station_key TEXT NOT NULL,
    energy_mix_index TEXT,
    current_revision_id INTEGER NOT NULL,
    FOREIGN KEY (datex_station_key) REFERENCES datex_energy_infrastructure_stations(datex_station_key),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS datex_rates (
    datex_rate_key TEXT PRIMARY KEY,
    datex_energy_mix_key TEXT NOT NULL,
    xsi_type TEXT,
    applicable_currency TEXT,
    overall_start_time_raw TEXT,
    current_revision_id INTEGER NOT NULL,
    FOREIGN KEY (datex_energy_mix_key) REFERENCES datex_electric_energy_mixes(datex_energy_mix_key),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS datex_rate_valid_periods (
    datex_valid_period_key TEXT PRIMARY KEY,
    datex_rate_key TEXT NOT NULL,
    period_ordinal INTEGER NOT NULL,
    xml_namespace_status TEXT NOT NULL,
    start_time_of_period_raw TEXT,
    end_time_of_period_raw TEXT,
    applicable_day_raw TEXT,
    applicable_day_canonical TEXT,
    current_revision_id INTEGER NOT NULL,
    FOREIGN KEY (datex_rate_key) REFERENCES datex_rates(datex_rate_key),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS datex_rate_period_names (
    datex_valid_period_key TEXT NOT NULL,
    text_index INTEGER NOT NULL,
    language TEXT,
    period_name TEXT,
    PRIMARY KEY (datex_valid_period_key, text_index),
    FOREIGN KEY (datex_valid_period_key) REFERENCES datex_rate_valid_periods(datex_valid_period_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS datex_energy_pricing_policies (
    datex_pricing_policy_key TEXT PRIMARY KEY,
    datex_rate_key TEXT NOT NULL,
    pricing_policy_raw TEXT,
    pricing_policy_canonical TEXT,
    current_revision_id INTEGER NOT NULL,
    FOREIGN KEY (datex_rate_key) REFERENCES datex_rates(datex_rate_key),
    FOREIGN KEY (current_revision_id) REFERENCES source_entity_revisions(source_entity_revision_id)
);

CREATE TABLE IF NOT EXISTS datex_pricing_additional_information (
    datex_pricing_policy_key TEXT NOT NULL,
    text_index INTEGER NOT NULL,
    language TEXT,
    raw_text TEXT,
    PRIMARY KEY (datex_pricing_policy_key, text_index),
    FOREIGN KEY (datex_pricing_policy_key) REFERENCES datex_energy_pricing_policies(datex_pricing_policy_key) ON DELETE CASCADE
);

-- DATEX II dynamic observations.
CREATE TABLE IF NOT EXISTS datex_dynamic_publications (
    datex_dynamic_publication_id INTEGER PRIMARY KEY,
    collection_run_id TEXT NOT NULL UNIQUE,
    publication_type TEXT NOT NULL,
    language TEXT,
    model_base_version TEXT,
    schema_location TEXT,
    feed_description TEXT,
    publication_time_raw TEXT,
    publication_time_utc TEXT,
    publication_creator_country TEXT,
    publication_creator_national_identifier TEXT,
    table_reference TEXT,
    raw_payload_id INTEGER NOT NULL,
    FOREIGN KEY (collection_run_id) REFERENCES collection_runs(collection_run_id),
    FOREIGN KEY (raw_payload_id) REFERENCES raw_payloads(raw_payload_id)
);

CREATE TABLE IF NOT EXISTS datex_site_status_observations (
    datex_site_status_observation_id INTEGER PRIMARY KEY,
    datex_dynamic_publication_id INTEGER NOT NULL,
    source_site_id TEXT NOT NULL,
    source_version TEXT,
    matched_datex_site_key TEXT,
    source_last_updated_raw TEXT,
    source_last_updated_utc TEXT,
    observed_at TEXT NOT NULL,
    source_timestamp_age_seconds REAL,
    source_timestamp_quality TEXT,
    UNIQUE (datex_dynamic_publication_id, source_site_id),
    FOREIGN KEY (datex_dynamic_publication_id) REFERENCES datex_dynamic_publications(datex_dynamic_publication_id) ON DELETE CASCADE,
    FOREIGN KEY (matched_datex_site_key) REFERENCES datex_energy_infrastructure_sites(datex_site_key)
);

CREATE TABLE IF NOT EXISTS datex_station_status_observations (
    datex_station_status_observation_id INTEGER PRIMARY KEY,
    datex_site_status_observation_id INTEGER NOT NULL,
    source_station_id TEXT NOT NULL,
    source_version TEXT,
    matched_datex_station_key TEXT,
    is_available_raw TEXT,
    is_available_boolean INTEGER,
    UNIQUE (datex_site_status_observation_id, source_station_id),
    FOREIGN KEY (datex_site_status_observation_id) REFERENCES datex_site_status_observations(datex_site_status_observation_id) ON DELETE CASCADE,
    FOREIGN KEY (matched_datex_station_key) REFERENCES datex_energy_infrastructure_stations(datex_station_key)
);

CREATE TABLE IF NOT EXISTS datex_refill_point_status_observations (
    datex_refill_status_observation_id INTEGER PRIMARY KEY,
    datex_station_status_observation_id INTEGER NOT NULL,
    source_status_id TEXT NOT NULL,
    connector_index_raw TEXT,
    connector_index_integer INTEGER,
    status_raw TEXT NOT NULL,
    status_canonical TEXT NOT NULL,
    UNIQUE (datex_station_status_observation_id, source_status_id),
    FOREIGN KEY (datex_station_status_observation_id) REFERENCES datex_station_status_observations(datex_station_status_observation_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS datex_dynamic_status_static_mappings (
    datex_refill_status_observation_id INTEGER NOT NULL,
    datex_refill_point_key TEXT,
    datex_connector_key TEXT,
    mapping_method TEXT NOT NULL,
    confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    mapping_evidence_json TEXT NOT NULL,
    PRIMARY KEY (datex_refill_status_observation_id),
    FOREIGN KEY (datex_refill_status_observation_id) REFERENCES datex_refill_point_status_observations(datex_refill_status_observation_id) ON DELETE CASCADE,
    FOREIGN KEY (datex_refill_point_key) REFERENCES datex_refill_points(datex_refill_point_key),
    FOREIGN KEY (datex_connector_key) REFERENCES datex_connectors(datex_connector_key)
);

-- Canonical real-world layer and explicit, revisable mappings.
CREATE TABLE IF NOT EXISTS charging_sites (
    charging_site_id TEXT PRIMARY KEY,
    preferred_name TEXT,
    representative_latitude REAL,
    representative_longitude REAL,
    physical_site_status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS charging_site_source_links (
    charging_site_source_link_id INTEGER PRIMARY KEY,
    charging_site_id TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_entity_type TEXT NOT NULL,
    source_entity_key TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    mapping_method TEXT NOT NULL,
    mapping_algorithm_version TEXT NOT NULL,
    confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    mapping_evidence_json TEXT NOT NULL,
    manually_verified INTEGER NOT NULL DEFAULT 0 CHECK (manually_verified IN (0, 1)),
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    UNIQUE (source_system, source_entity_type, source_entity_key, valid_from),
    FOREIGN KEY (charging_site_id) REFERENCES charging_sites(charging_site_id)
);

CREATE TABLE IF NOT EXISTS charging_equipment (
    charging_equipment_id TEXT PRIMARY KEY,
    charging_site_id TEXT NOT NULL,
    equipment_level TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (charging_site_id) REFERENCES charging_sites(charging_site_id)
);

CREATE TABLE IF NOT EXISTS charging_equipment_source_links (
    charging_equipment_source_link_id INTEGER PRIMARY KEY,
    charging_equipment_id TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_entity_type TEXT NOT NULL,
    source_entity_key TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    mapping_cardinality TEXT NOT NULL,
    mapping_method TEXT NOT NULL,
    mapping_algorithm_version TEXT NOT NULL,
    confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    mapping_evidence_json TEXT NOT NULL,
    manually_verified INTEGER NOT NULL DEFAULT 0 CHECK (manually_verified IN (0, 1)),
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    UNIQUE (source_system, source_entity_type, source_entity_key, charging_equipment_id, valid_from),
    FOREIGN KEY (charging_equipment_id) REFERENCES charging_equipment(charging_equipment_id)
);

CREATE INDEX IF NOT EXISTS index_collection_runs_endpoint_time
ON collection_runs(source_endpoint_id, started_at);
CREATE INDEX IF NOT EXISTS index_source_entity_observations_run
ON source_entity_observations(collection_run_id);
CREATE INDEX IF NOT EXISTS index_ocpi_location_coordinates
ON ocpi_locations(latitude, longitude);
CREATE INDEX IF NOT EXISTS index_ocpi_evse_status_time
ON ocpi_evse_status_observations(ocpi_evse_key, observed_at);
CREATE INDEX IF NOT EXISTS index_datex_station_coordinates
ON datex_energy_infrastructure_stations(latitude, longitude);
CREATE INDEX IF NOT EXISTS index_datex_site_source_identifier
ON datex_energy_infrastructure_sites(source_site_id, is_current);
CREATE INDEX IF NOT EXISTS index_datex_station_source_identifier
ON datex_energy_infrastructure_stations(source_station_id, is_current);
CREATE INDEX IF NOT EXISTS index_datex_refill_station
ON datex_refill_points(datex_station_key, ordinal_within_station, is_current);
CREATE INDEX IF NOT EXISTS index_datex_connector_refill
ON datex_connectors(datex_refill_point_key, connector_ordinal, is_current);
CREATE INDEX IF NOT EXISTS index_datex_dynamic_station
ON datex_station_status_observations(source_station_id);
CREATE INDEX IF NOT EXISTS index_charging_site_source_entity
ON charging_site_source_links(source_system, source_entity_type, source_entity_key, is_current);
CREATE INDEX IF NOT EXISTS index_charging_equipment_source_entity
ON charging_equipment_source_links(source_system, source_entity_type, source_entity_key, is_current);
