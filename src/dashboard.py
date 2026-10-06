"""Read-only real-time explorer for the OCPI and DATEX II database v2."""

from datetime import datetime, timezone
import json
import sqlite3

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from database_v2 import DATABASE_PATH


REFRESH_SECONDS = 30
STATUS_COLORS = {
    "available": "#22c55e",
    "charging": "#3b82f6",
    "inoperative": "#f59e0b",
    "outoforder": "#ef4444",
    "out_of_order": "#ef4444",
    "removed": "#475569",
    "unknown": "#94a3b8",
}


st.set_page_config(
    page_title="Matemafija Data Explorer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1800px;}
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, #101827, #111d31);
        border: 1px solid #26364e;
        border-radius: 12px;
        padding: 13px 15px;
    }
    [data-testid="stMetricLabel"] {color: #9aabc2;}
    [data-testid="stMetricValue"] {color: #f8fafc;}
    .explorer-subtitle {color: #91a2ba; margin-top: -0.8rem; margin-bottom: 1rem;}
    .source-badge {
        display: inline-block; padding: 0.18rem 0.55rem; border-radius: 999px;
        background: #172338; color: #b9c8dc; border: 1px solid #2b3d57;
        font-size: 0.78rem; margin-right: 0.35rem;
    }
    .direct-note {
        padding: 0.75rem 1rem; border-left: 4px solid #38bdf8;
        background: #0e1b2d; border-radius: 0 8px 8px 0; color: #cbd5e1;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def open_read_connection():
    """Open SQLite in read-only mode while collectors may write in WAL mode."""
    connection = sqlite3.connect(
        f"file:{DATABASE_PATH}?mode=ro",
        uri=True,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def frame(connection, query, parameters=()):
    return pd.read_sql_query(query, connection, params=parameters)


def table_exists(connection, table_name):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone() is not None


def scalar(connection, query, parameters=(), default=0):
    row = connection.execute(query, parameters).fetchone()
    if row is None or row[0] is None:
        return default
    return row[0]


def local_time(value):
    if value is None or value == "":
        return "—"
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.tz_convert("Europe/Vilnius").strftime("%Y-%m-%d %H:%M:%S")


def age_label(value):
    if not value:
        return "—"
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return "invalid timestamp"
    seconds = max(
        0,
        int((datetime.now(timezone.utc) - parsed.to_pydatetime()).total_seconds()),
    )
    if seconds < 120:
        return f"{seconds} sec"
    if seconds < 7200:
        return f"{seconds // 60} min"
    if seconds < 172800:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} days"


def pretty_json(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def render_empty_state(connection):
    st.warning("Database v2 exists, but it has no completed source collection yet.")
    st.markdown(
        "Run one complete collection from the project directory:"
    )
    st.code("python src/collect.py --once", language="bash")
    if table_exists(connection, "status_history"):
        legacy = scalar(connection, "SELECT COUNT(*) FROM status_history")
        st.info(
            f"The legacy database still contains {legacy:,} OCPI status rows. "
            "They remain available to the old schema and have not been deleted."
        )


def latest_run_summary(connection):
    return frame(
        connection,
        """
        SELECT
            source_endpoints.endpoint_type,
            collection_runs.collection_run_id,
            collection_runs.started_at,
            collection_runs.completed_at,
            collection_runs.run_status,
            collection_runs.is_complete_snapshot,
            collection_runs.records_received,
            collection_runs.records_accepted,
            collection_runs.records_rejected,
            collection_runs.server_publication_time_utc,
            ROW_NUMBER() OVER (
                PARTITION BY source_endpoints.endpoint_type
                ORDER BY collection_runs.started_at DESC
            ) AS recency_rank
        FROM collection_runs
        JOIN source_endpoints USING (source_endpoint_id)
        """,
    )


def render_header(connection):
    runs = latest_run_summary(connection)
    latest = runs[runs["recency_rank"] == 1].copy()
    latest_completed = latest["completed_at"].dropna().max() if not latest.empty else None

    st.title("Matemafija EV data explorer")
    st.markdown(
        '<p class="explorer-subtitle">OCPI + DATEX II source facts, database structure, provenance and explicit relationships</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="direct-note">
        This interface visualizes observed and normalized source data only.
        Queue length, idle time, congestion scores, adaptive fees and other model
        variables are intentionally not calculated here.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Latest completed database write: "
        + (local_time(latest_completed) if latest_completed else "none")
        + " · age " + age_label(latest_completed)
    )
    return latest


def render_overview(connection, latest_runs):
    st.subheader("Current database coverage")
    counts = {
        "OCPI locations": scalar(connection, "SELECT COUNT(*) FROM ocpi_locations WHERE is_current=1"),
        "OCPI EVSEs": scalar(connection, "SELECT COUNT(*) FROM ocpi_evses WHERE is_current=1"),
        "OCPI connectors": scalar(connection, "SELECT COUNT(*) FROM ocpi_connectors WHERE is_current=1"),
        "DATEX stations": scalar(connection, "SELECT COUNT(*) FROM datex_energy_infrastructure_stations WHERE is_current=1"),
        "DATEX refill points": scalar(connection, "SELECT COUNT(*) FROM datex_refill_points WHERE is_current=1"),
        "DATEX connectors": scalar(connection, "SELECT COUNT(*) FROM datex_connectors WHERE is_current=1"),
        "Canonical sites": scalar(connection, "SELECT COUNT(*) FROM charging_sites"),
        "Open quality issues": scalar(connection, "SELECT COUNT(*) FROM data_quality_issues WHERE resolved_at IS NULL"),
    }
    metric_columns = st.columns(4)
    for index, (label, value) in enumerate(counts.items()):
        metric_columns[index % 4].metric(label, f"{int(value):,}")

    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("#### Latest run per endpoint")
        display = latest_runs.drop(columns=["recency_rank"], errors="ignore").copy()
        if not display.empty:
            display["completed_at"] = display["completed_at"].map(local_time)
            display["server_publication_time_utc"] = display[
                "server_publication_time_utc"
            ].map(local_time)
        st.dataframe(display, hide_index=True, width="stretch")
    with right:
        run_counts = frame(
            connection,
            """
            SELECT source_endpoints.endpoint_type, collection_runs.run_status,
                   COUNT(*) AS run_count
            FROM collection_runs
            JOIN source_endpoints USING (source_endpoint_id)
            GROUP BY source_endpoints.endpoint_type, collection_runs.run_status
            """,
        )
        if not run_counts.empty:
            chart = px.bar(
                run_counts,
                x="endpoint_type",
                y="run_count",
                color="run_status",
                title="Collection runs by endpoint and result",
                barmode="stack",
            )
            chart.update_layout(xaxis_title="", yaxis_title="Runs")
            st.plotly_chart(chart, width="stretch")

    st.markdown("#### Current source status counts")
    ocpi_statuses = frame(
        connection,
        """SELECT source_status_canonical AS status, COUNT(*) AS records,
                  'OCPI EVSE' AS source
           FROM ocpi_evses WHERE is_current=1
           GROUP BY source_status_canonical""",
    )
    datex_statuses = frame(
        connection,
        """SELECT status_canonical AS status, COUNT(*) AS records,
                  'DATEX latest publication' AS source
           FROM datex_refill_point_status_observations
           WHERE datex_station_status_observation_id IN (
             SELECT datex_station_status_observation_id
             FROM datex_station_status_observations
             JOIN datex_site_status_observations USING (datex_site_status_observation_id)
             WHERE datex_dynamic_publication_id=(
               SELECT MAX(datex_dynamic_publication_id) FROM datex_dynamic_publications
             )
           ) GROUP BY status_canonical""",
    )
    status_data = pd.concat([ocpi_statuses, datex_statuses], ignore_index=True)
    if not status_data.empty:
        chart = px.bar(
            status_data,
            x="status",
            y="records",
            color="source",
            barmode="group",
            title="Direct source status counts; granularities may differ",
        )
        st.plotly_chart(chart, width="stretch")
        st.caption(
            "OCPI EVSE and DATEX refillPointStatus are displayed side by side, "
            "not added together: their physical granularity is not guaranteed to match."
        )


def render_ocpi(connection):
    st.subheader("OCPI source explorer")
    locations = frame(
        connection,
        """
        SELECT ocpi_location_key, source_location_id, name, city, address,
               latitude, longitude, parking_type, time_zone, publish,
               charging_when_closed, source_last_updated_raw,
               source_last_updated_utc, last_seen_at, is_current
        FROM ocpi_locations ORDER BY city, name
        """,
    )
    if locations.empty:
        st.info("No OCPI v2 locations have been collected yet.")
        return

    cities = ["All", *sorted(x for x in locations["city"].dropna().unique() if x)]
    selected_city = st.selectbox("City", cities, key="ocpi_city")
    current_only = st.toggle("Current locations only", True, key="ocpi_current")
    filtered = locations.copy()
    if selected_city != "All":
        filtered = filtered[filtered["city"] == selected_city]
    if current_only:
        filtered = filtered[filtered["is_current"] == 1]

    map_data = filtered.dropna(subset=["latitude", "longitude"])
    if not map_data.empty:
        map_chart = px.scatter_map(
            map_data,
            lat="latitude",
            lon="longitude",
            hover_name="name",
            hover_data=["source_location_id", "city", "address", "parking_type"],
            zoom=9 if selected_city != "All" else 6,
            height=420,
        )
        map_chart.update_layout(map_style="carto-positron", margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(map_chart, width="stretch")

    labels = {
        row.ocpi_location_key: f"{row.source_location_id} · {row.name or 'Unnamed'} · {row.city or '—'}"
        for row in filtered.itertuples()
    }
    if not labels:
        st.info("No locations match the selected filters.")
        return
    selected_key = st.selectbox(
        "Inspect location",
        list(labels),
        format_func=labels.get,
        key="ocpi_location",
    )
    location = filtered[filtered["ocpi_location_key"] == selected_key].iloc[0]
    detail_columns = st.columns(4)
    detail_columns[0].metric("Source location ID", location["source_location_id"])
    detail_columns[1].metric("City", location["city"] or "—")
    detail_columns[2].metric("Source updated", age_label(location["source_last_updated_utc"]))
    detail_columns[3].metric("Collector last saw", age_label(location["last_seen_at"]))

    organizations = frame(
        connection,
        """SELECT organization_role, organization_name, website, valid_from,
                  valid_to, ocpi_location_organization_roles.is_current
           FROM ocpi_location_organization_roles
           JOIN ocpi_organizations USING (ocpi_organization_key)
           WHERE ocpi_location_key=? ORDER BY organization_role, valid_from""",
        (selected_key,),
    )
    evses = frame(
        connection,
        """SELECT ocpi_evse_key, source_uid, public_evse_id, physical_reference,
                  source_status_raw, source_status_canonical,
                  source_last_updated_raw, source_last_updated_utc,
                  first_seen_at, last_seen_at, missing_since, is_current
           FROM ocpi_evses WHERE ocpi_location_key=?
           ORDER BY public_evse_id, source_uid""",
        (selected_key,),
    )
    connectors = frame(
        connection,
        """SELECT ocpi_connectors.ocpi_connector_key,
                  ocpi_evses.public_evse_id, ocpi_connectors.source_connector_id,
                  connector_standard, connector_format, power_type,
                  voltage_v, amperage_a, max_electric_power_w,
                  terms_and_conditions_url, ocpi_connectors.source_last_updated_raw,
                  ocpi_connectors.is_current
           FROM ocpi_connectors JOIN ocpi_evses USING (ocpi_evse_key)
           WHERE ocpi_evses.ocpi_location_key=?
           ORDER BY ocpi_evses.public_evse_id, ocpi_connectors.source_connector_id""",
        (selected_key,),
    )

    tab_identity, tab_equipment, tab_metadata, tab_history, tab_raw = st.tabs(
        ["Identity", "EVSEs & connectors", "Metadata", "Status history", "Normalized & raw"]
    )
    with tab_identity:
        st.dataframe(
            pd.DataFrame([location.to_dict()]),
            hide_index=True,
            width="stretch",
        )
        st.markdown("##### Organization roles")
        st.dataframe(organizations, hide_index=True, width="stretch")
    with tab_equipment:
        st.markdown("##### EVSE records")
        st.dataframe(evses, hide_index=True, width="stretch")
        st.markdown("##### Connector records")
        st.dataframe(connectors, hide_index=True, width="stretch")
        if not connectors.empty:
            connector_chart = px.bar(
                connectors,
                x="public_evse_id",
                y="max_electric_power_w",
                color="connector_standard",
                hover_data=["power_type", "voltage_v", "amperage_a"],
                title="Published maximum electric power by OCPI connector",
            )
            st.plotly_chart(connector_chart, width="stretch")
    with tab_metadata:
        revision_id = scalar(
            connection,
            "SELECT current_revision_id FROM ocpi_locations WHERE ocpi_location_key=?",
            (selected_key,),
            None,
        )
        metadata_queries = {
            "Directions": "SELECT direction_index, language, direction_text FROM ocpi_location_directions WHERE source_entity_revision_id=?",
            "Facilities": "SELECT facility_index, facility_code FROM ocpi_location_facilities WHERE source_entity_revision_id=?",
            "Images": "SELECT * FROM ocpi_location_images WHERE source_entity_revision_id=?",
            "Opening times": "SELECT * FROM ocpi_location_opening_times WHERE source_entity_revision_id=?",
            "Regular hours": "SELECT * FROM ocpi_location_regular_hours WHERE source_entity_revision_id=?",
            "Parking places": "SELECT * FROM ocpi_parking_places WHERE ocpi_location_key=?",
            "Energy mix": "SELECT * FROM ocpi_location_energy_mix WHERE source_entity_revision_id=?",
        }
        for title, query in metadata_queries.items():
            st.markdown(f"##### {title}")
            st.dataframe(frame(connection, query, (revision_id if title != "Parking places" else selected_key,)),
                         hide_index=True, width="stretch")
    with tab_history:
        history = frame(
            connection,
            """SELECT observed_at, public_evse_id, status_raw, status_canonical,
                      ocpi_evse_status_observations.source_last_updated_raw,
                      source_timestamp_age_seconds,
                      source_timestamp_quality, collection_run_id
               FROM ocpi_evse_status_observations
               JOIN ocpi_evses USING (ocpi_evse_key)
               WHERE ocpi_location_key=? ORDER BY observed_at""",
            (selected_key,),
        )
        st.dataframe(history.sort_values("observed_at", ascending=False), hide_index=True, width="stretch")
        if not history.empty:
            counts = history.groupby(["observed_at", "status_canonical"]).size().reset_index(name="records")
            chart = px.line(counts, x="observed_at", y="records", color="status_canonical",
                            markers=True, title="Observed OCPI status counts per collection")
            st.plotly_chart(chart, width="stretch")
    with tab_raw:
        render_entity_revision_explorer(connection, "ocpi_location", selected_key, embedded=True)


def render_datex_static(connection):
    st.subheader("DATEX II static infrastructure explorer")
    stations = frame(
        connection,
        """SELECT datex_station_key, source_station_id, source_version,
                  source_last_updated_raw, source_last_updated_utc,
                  latitude, longitude, number_of_refill_points,
                  datex_site_key, is_current
           FROM datex_energy_infrastructure_stations
           ORDER BY source_station_id""",
    )
    if stations.empty:
        st.info("No DATEX static publication has been collected yet.")
        return
    query = st.text_input("Find station ID", placeholder="EGI-ST-258")
    current_only = st.toggle("Current DATEX stations only", True, key="datex_static_current")
    filtered = stations.copy()
    if current_only:
        filtered = filtered[filtered["is_current"] == 1]
    if query:
        filtered = filtered[filtered["source_station_id"].str.contains(query, case=False, na=False)]
    labels = {
        row.datex_station_key: f"{row.source_station_id} · {row.number_of_refill_points} declared refill points"
        for row in filtered.head(1000).itertuples()
    }
    if not labels:
        st.info("No station matches the search.")
        return
    station_key = st.selectbox("Inspect DATEX station", list(labels), format_func=labels.get)
    station = stations[stations["datex_station_key"] == station_key].iloc[0]

    provider = frame(
        connection,
        """SELECT organization_role, organization_name,
                  organization_description, link_to_general_information,
                  telephone_number, source_last_updated_raw
           FROM datex_station_organization_roles
           JOIN datex_organizations USING (datex_organization_key)
           WHERE datex_station_key=? AND datex_station_organization_roles.is_current=1""",
        (station_key,),
    )
    refills = frame(
        connection,
        """SELECT datex_refill_point_key, source_refill_point_id,
                  source_version, xsi_type, usage_type,
                  ordinal_within_station, is_current
           FROM datex_refill_points WHERE datex_station_key=?
           ORDER BY ordinal_within_station""",
        (station_key,),
    )
    connectors = frame(
        connection,
        """SELECT datex_connectors.datex_connector_key,
                  datex_refill_points.source_refill_point_id,
                  datex_connectors.connector_ordinal,
                  datex_connectors.connector_type_raw,
                  datex_connectors.connector_type_canonical,
                  datex_connectors.max_power_at_socket_raw,
                  datex_connectors.max_power_at_socket_kw,
                  datex_connectors.unit_interpretation_status,
                  datex_connectors.content_fingerprint,
                  datex_connectors.is_current
           FROM datex_connectors
           JOIN datex_refill_points USING (datex_refill_point_key)
           WHERE datex_refill_points.datex_station_key=?
           ORDER BY datex_refill_points.ordinal_within_station,
                    datex_connectors.connector_ordinal""",
        (station_key,),
    )
    rates = frame(
        connection,
        """SELECT datex_rates.datex_rate_key, energy_mix_index,
                  datex_rates.xsi_type, applicable_currency,
                  overall_start_time_raw, pricing_policy_raw,
                  pricing_policy_canonical
           FROM datex_electric_energy_mixes
           JOIN datex_rates USING (datex_energy_mix_key)
           LEFT JOIN datex_energy_pricing_policies USING (datex_rate_key)
           WHERE datex_station_key=?""",
        (station_key,),
    )
    price_texts = frame(
        connection,
        """SELECT datex_pricing_additional_information.*
           FROM datex_pricing_additional_information
           JOIN datex_energy_pricing_policies USING (datex_pricing_policy_key)
           JOIN datex_rates USING (datex_rate_key)
           JOIN datex_electric_energy_mixes USING (datex_energy_mix_key)
           WHERE datex_station_key=? ORDER BY text_index""",
        (station_key,),
    )
    periods = frame(
        connection,
        """SELECT datex_rate_valid_periods.*, language, period_name
           FROM datex_rate_valid_periods
           LEFT JOIN datex_rate_period_names USING (datex_valid_period_key)
           JOIN datex_rates USING (datex_rate_key)
           JOIN datex_electric_energy_mixes USING (datex_energy_mix_key)
           WHERE datex_station_key=? ORDER BY period_ordinal, text_index""",
        (station_key,),
    )

    metrics = st.columns(5)
    metrics[0].metric("Station", station["source_station_id"])
    metrics[1].metric("Declared refill points", int(station["number_of_refill_points"] or 0))
    metrics[2].metric("Refill rows", len(refills))
    metrics[3].metric("Connector rows", len(connectors))
    metrics[4].metric("Source updated", age_label(station["source_last_updated_utc"]))
    identity_tab, equipment_tab, rate_tab, raw_tab = st.tabs(
        ["Station & provider", "Refill points & connectors", "Rates & periods", "Normalized & raw"]
    )
    with identity_tab:
        st.dataframe(pd.DataFrame([station.to_dict()]), hide_index=True, width="stretch")
        st.dataframe(provider, hide_index=True, width="stretch")
    with equipment_tab:
        st.markdown("##### Refill points")
        st.dataframe(refills, hide_index=True, width="stretch")
        st.markdown("##### Connectors")
        st.dataframe(connectors, hide_index=True, width="stretch")
        if not connectors.empty:
            chart = px.bar(
                connectors,
                x="source_refill_point_id",
                y="max_power_at_socket_kw",
                color="connector_type_raw",
                hover_data=["connector_ordinal", "max_power_at_socket_raw", "unit_interpretation_status"],
                title="DATEX connector records and published maxPowerAtSocket",
            )
            st.plotly_chart(chart, width="stretch")
    with rate_tab:
        st.markdown("##### Rates")
        st.dataframe(rates, hide_index=True, width="stretch")
        st.markdown("##### Public textual price information")
        st.dataframe(price_texts, hide_index=True, width="stretch")
        st.markdown("##### Valid periods")
        st.dataframe(periods, hide_index=True, width="stretch")
    with raw_tab:
        render_entity_revision_explorer(connection, "datex_station", station_key, embedded=True)


def render_datex_dynamic(connection):
    st.subheader("DATEX II dynamic observation explorer")
    publications = frame(
        connection,
        """SELECT datex_dynamic_publication_id, collection_run_id,
                  publication_time_raw, publication_time_utc,
                  publication_creator_country,
                  publication_creator_national_identifier,
                  table_reference
           FROM datex_dynamic_publications
           ORDER BY datex_dynamic_publication_id DESC""",
    )
    if publications.empty:
        st.info("No DATEX dynamic publication has been collected yet.")
        return
    publication_options = publications["datex_dynamic_publication_id"].tolist()
    selected_publication = st.selectbox(
        "Publication",
        publication_options,
        format_func=lambda value: (
            f"#{value} · "
            + local_time(publications.loc[
                publications["datex_dynamic_publication_id"] == value,
                "publication_time_utc",
            ].iloc[0])
        ),
    )
    statuses = frame(
        connection,
        """SELECT datex_station_status_observations.source_station_id,
                  matched_datex_station_key, is_available_raw,
                  source_status_id, connector_index_raw,
                  connector_index_integer, status_raw, status_canonical,
                  source_last_updated_raw, source_last_updated_utc,
                  source_timestamp_age_seconds, source_timestamp_quality,
                  datex_refill_point_key, datex_connector_key,
                  mapping_method, confidence_score, mapping_evidence_json
           FROM datex_refill_point_status_observations
           JOIN datex_station_status_observations USING (datex_station_status_observation_id)
           JOIN datex_site_status_observations USING (datex_site_status_observation_id)
           LEFT JOIN datex_dynamic_status_static_mappings
             USING (datex_refill_status_observation_id)
           WHERE datex_dynamic_publication_id=?
           ORDER BY source_station_id, connector_index_integer""",
        (selected_publication,),
    )
    site_rows = scalar(
        connection,
        "SELECT COUNT(*) FROM datex_site_status_observations WHERE datex_dynamic_publication_id=?",
        (selected_publication,),
    )
    station_rows = scalar(
        connection,
        """SELECT COUNT(*) FROM datex_station_status_observations
           JOIN datex_site_status_observations USING (datex_site_status_observation_id)
           WHERE datex_dynamic_publication_id=?""",
        (selected_publication,),
    )
    metrics = st.columns(5)
    metrics[0].metric("Site status rows", f"{site_rows:,}")
    metrics[1].metric("Station status rows", f"{station_rows:,}")
    metrics[2].metric("Refill status rows", f"{len(statuses):,}")
    metrics[3].metric("Mapped status rows", f"{int(statuses['mapping_method'].notna().sum()):,}")
    metrics[4].metric("Unmapped status rows", f"{int(statuses['mapping_method'].isna().sum()):,}")

    left, right = st.columns([1, 1.4])
    with left:
        distribution = statuses.groupby(["status_raw", "status_canonical"]).size().reset_index(name="records")
        chart = px.bar(distribution, x="status_raw", y="records", color="status_canonical",
                       title="Raw and canonical DATEX statuses")
        st.plotly_chart(chart, width="stretch")
    with right:
        quality = statuses.groupby("source_timestamp_quality", dropna=False).size().reset_index(name="records")
        chart = px.bar(quality, x="source_timestamp_quality", y="records",
                       title="Source timestamp quality")
        st.plotly_chart(chart, width="stretch")

    station_ids = statuses["source_station_id"].dropna().unique().tolist()
    station_search = st.text_input("Filter station ID", placeholder="EGI-ST-258", key="dynamic_station_search")
    if station_search:
        station_ids = [value for value in station_ids if station_search.casefold() in value.casefold()]
    if station_ids:
        station_id = st.selectbox("Inspect station statuses", station_ids[:1000])
        station_statuses = statuses[statuses["source_station_id"] == station_id].copy()
        st.dataframe(station_statuses, hide_index=True, width="stretch")
        evidence_rows = station_statuses[station_statuses["mapping_evidence_json"].notna()]
        if not evidence_rows.empty:
            with st.expander("Mapping evidence for selected status rows"):
                for row in evidence_rows.itertuples():
                    st.markdown(f"**Status ID {row.source_status_id} — {row.mapping_method} ({row.confidence_score:.2f})**")
                    st.json(pretty_json(row.mapping_evidence_json))

    st.markdown("#### History for one DATEX station")
    all_station_ids = frame(
        connection,
        "SELECT DISTINCT source_station_id FROM datex_station_status_observations ORDER BY source_station_id",
    )["source_station_id"].tolist()
    if all_station_ids:
        history_station = st.selectbox("Station history", all_station_ids, key="datex_station_history")
        history = frame(
            connection,
            """SELECT datex_dynamic_publications.publication_time_utc,
                      datex_site_status_observations.observed_at,
                      source_status_id, connector_index_raw, status_raw,
                      status_canonical, source_last_updated_raw,
                      source_timestamp_quality
               FROM datex_refill_point_status_observations
               JOIN datex_station_status_observations USING (datex_station_status_observation_id)
               JOIN datex_site_status_observations USING (datex_site_status_observation_id)
               JOIN datex_dynamic_publications USING (datex_dynamic_publication_id)
               WHERE source_station_id=? ORDER BY observed_at""",
            (history_station,),
        )
        st.dataframe(history.sort_values("observed_at", ascending=False), hide_index=True, width="stretch")
        if not history.empty:
            counts = history.groupby(["observed_at", "status_canonical"]).size().reset_index(name="records")
            st.plotly_chart(
                px.line(counts, x="observed_at", y="records", color="status_canonical", markers=True,
                        title="Direct DATEX status counts over observations"),
                width="stretch",
            )


def render_relationships(connection):
    st.subheader("Explicit OCPI ↔ DATEX relationships")
    st.caption(
        "Mappings are database assertions with provenance and confidence. "
        "They do not overwrite either source."
    )
    site_links = frame(
        connection,
        """SELECT charging_site_id, source_system, source_entity_type,
                  source_entity_key, relation_type, mapping_method,
                  mapping_algorithm_version, confidence_score,
                  mapping_evidence_json, manually_verified, review_status,
                  valid_from, valid_to, is_current
           FROM charging_site_source_links
           ORDER BY charging_site_id, source_system""",
    )
    equipment_links = frame(
        connection,
        """SELECT charging_equipment.charging_site_id,
                  charging_equipment_source_links.*
           FROM charging_equipment_source_links
           JOIN charging_equipment USING (charging_equipment_id)
           ORDER BY charging_site_id, charging_equipment_id, source_system""",
    )
    metrics = st.columns(5)
    metrics[0].metric("Canonical sites", scalar(connection, "SELECT COUNT(*) FROM charging_sites"))
    metrics[1].metric("Current site links", int((site_links["is_current"] == 1).sum()) if not site_links.empty else 0)
    metrics[2].metric("Canonical equipment", scalar(connection, "SELECT COUNT(*) FROM charging_equipment"))
    metrics[3].metric("Current equipment links", int((equipment_links["is_current"] == 1).sum()) if not equipment_links.empty else 0)
    metrics[4].metric("Manually verified", int(equipment_links["manually_verified"].sum()) if not equipment_links.empty else 0)

    site_tab, equipment_tab, compare_tab = st.tabs(
        ["Site links", "Equipment links", "Compare one canonical site"]
    )
    with site_tab:
        if site_links.empty:
            st.info("No site mappings yet.")
        else:
            minimum_confidence = st.slider("Minimum site-link confidence", 0.0, 1.0, 0.0, 0.05)
            current = st.toggle("Current links only", True, key="site_links_current")
            filtered = site_links[site_links["confidence_score"] >= minimum_confidence]
            if current:
                filtered = filtered[filtered["is_current"] == 1]
            st.dataframe(filtered.drop(columns=["mapping_evidence_json"]), hide_index=True, width="stretch")
            methods = filtered.groupby(["mapping_method", "source_system"]).size().reset_index(name="links")
            if not methods.empty:
                st.plotly_chart(px.bar(methods, x="mapping_method", y="links", color="source_system",
                                       title="Site mappings by method and source"), width="stretch")
    with equipment_tab:
        if equipment_links.empty:
            st.info("No equipment mappings yet.")
        else:
            minimum_confidence = st.slider("Minimum equipment-link confidence", 0.0, 1.0, 0.0, 0.05)
            filtered = equipment_links[equipment_links["confidence_score"] >= minimum_confidence]
            st.dataframe(filtered.drop(columns=["mapping_evidence_json"]), hide_index=True, width="stretch")
            link_flow = filtered.groupby(["source_entity_type", "relation_type"]).size().reset_index(name="links")
            st.plotly_chart(px.bar(link_flow, x="source_entity_type", y="links", color="relation_type",
                                   title="Equipment relations and cardinality roles"), width="stretch")
    with compare_tab:
        canonical_sites = frame(
            connection,
            """SELECT charging_sites.charging_site_id, preferred_name,
                      COUNT(charging_site_source_link_id) AS source_links
               FROM charging_sites
               LEFT JOIN charging_site_source_links USING (charging_site_id)
               WHERE charging_site_source_links.is_current=1
               GROUP BY charging_sites.charging_site_id, preferred_name
               HAVING COUNT(charging_site_source_link_id)>1
               ORDER BY preferred_name, charging_sites.charging_site_id""",
        )
        if canonical_sites.empty:
            st.info("No multi-source canonical site is available yet.")
        else:
            labels = {
                row.charging_site_id: f"{row.preferred_name or 'Unnamed'} · {row.source_links} source links"
                for row in canonical_sites.itertuples()
            }
            site_id = st.selectbox("Canonical site", list(labels), format_func=labels.get)
            comparison = frame(
                connection,
                """SELECT source_system, source_entity_type, source_entity_key,
                          relation_type, mapping_method, confidence_score,
                          mapping_evidence_json
                   FROM charging_site_source_links
                   WHERE charging_site_id=? AND is_current=1""",
                (site_id,),
            )
            st.dataframe(comparison.drop(columns=["mapping_evidence_json"]), hide_index=True, width="stretch")
            ocpi_key_rows = comparison.loc[comparison["source_entity_type"] == "OCPI_LOCATION", "source_entity_key"]
            datex_key_rows = comparison.loc[comparison["source_entity_type"] == "DATEX_STATION", "source_entity_key"]
            left, right = st.columns(2)
            with left:
                st.markdown("##### OCPI location facts")
                if not ocpi_key_rows.empty:
                    st.dataframe(frame(connection, "SELECT * FROM ocpi_locations WHERE ocpi_location_key=?",
                                       (ocpi_key_rows.iloc[0],)), hide_index=True, width="stretch")
            with right:
                st.markdown("##### DATEX station facts")
                if not datex_key_rows.empty:
                    st.dataframe(frame(connection, "SELECT * FROM datex_energy_infrastructure_stations WHERE datex_station_key=?",
                                       (datex_key_rows.iloc[0],)), hide_index=True, width="stretch")
            st.markdown("##### Mapping evidence")
            for row in comparison.itertuples():
                st.markdown(f"**{row.source_system} · {row.mapping_method} · confidence {row.confidence_score:.2f}**")
                st.json(pretty_json(row.mapping_evidence_json))


def render_quality(connection):
    st.subheader("Data quality and completeness")
    issues = frame(
        connection,
        """SELECT data_quality_issue_id, detected_at, issue_code, severity,
                  source_entity_type, source_entity_key, field_path,
                  raw_value, issue_description, resolved_at, collection_run_id
           FROM data_quality_issues ORDER BY detected_at DESC, issue_code""",
    )
    left, right = st.columns(2)
    with left:
        if not issues.empty:
            summary = issues.groupby(["issue_code", "severity"]).size().reset_index(name="issues")
            st.plotly_chart(px.bar(summary, x="issue_code", y="issues", color="severity",
                                   title="Recorded quality issues"), width="stretch")
        else:
            st.info("No quality issue has been recorded.")
    with right:
        missing = frame(
            connection,
            """
            SELECT 'ocpi_locations' AS entity_type, COUNT(*) AS missing FROM ocpi_locations WHERE is_current=0
            UNION ALL SELECT 'ocpi_evses', COUNT(*) FROM ocpi_evses WHERE is_current=0
            UNION ALL SELECT 'ocpi_connectors', COUNT(*) FROM ocpi_connectors WHERE is_current=0
            UNION ALL SELECT 'ocpi_tariffs', COUNT(*) FROM ocpi_tariffs WHERE is_current=0
            UNION ALL SELECT 'datex_sites', COUNT(*) FROM datex_energy_infrastructure_sites WHERE is_current=0
            UNION ALL SELECT 'datex_stations', COUNT(*) FROM datex_energy_infrastructure_stations WHERE is_current=0
            UNION ALL SELECT 'datex_refill_points', COUNT(*) FROM datex_refill_points WHERE is_current=0
            UNION ALL SELECT 'datex_connectors', COUNT(*) FROM datex_connectors WHERE is_current=0
            """,
        )
        st.plotly_chart(px.bar(missing, x="entity_type", y="missing",
                               title="Entities absent from the latest complete snapshot"), width="stretch")
    if not issues.empty:
        codes = ["All", *sorted(issues["issue_code"].unique())]
        selected = st.selectbox("Issue code", codes)
        display = issues if selected == "All" else issues[issues["issue_code"] == selected]
        st.dataframe(display, hide_index=True, width="stretch")

    st.markdown("#### Timestamp quality in direct observations")
    timestamp_quality = frame(
        connection,
        """
        SELECT 'OCPI EVSE' AS source, source_timestamp_quality, COUNT(*) AS observations
        FROM ocpi_evse_status_observations GROUP BY source_timestamp_quality
        UNION ALL
        SELECT 'DATEX site', source_timestamp_quality, COUNT(*)
        FROM datex_site_status_observations GROUP BY source_timestamp_quality
        """,
    )
    st.dataframe(timestamp_quality, hide_index=True, width="stretch")


def render_entity_revision_explorer(connection, default_type=None,
                                    default_key=None, embedded=False):
    if not embedded:
        st.subheader("Revision and observation explorer")
        st.caption(
            "A revision is unique content; an observation records every run in which that content was seen."
        )
    entity_types = frame(
        connection,
        """SELECT source_entity_type, COUNT(DISTINCT source_entity_key) AS entities,
                  COUNT(*) AS revisions
           FROM source_entity_revisions GROUP BY source_entity_type
           ORDER BY source_entity_type""",
    )
    if entity_types.empty:
        st.info("No source revisions yet.")
        return
    types = entity_types["source_entity_type"].tolist()
    default_index = types.index(default_type) if default_type in types else 0
    entity_type = default_type if embedded and default_type else st.selectbox(
        "Entity type", types, index=default_index
    )
    keys = frame(
        connection,
        """SELECT source_entity_key, COUNT(*) AS revisions
           FROM source_entity_revisions WHERE source_entity_type=?
           GROUP BY source_entity_key ORDER BY source_entity_key""",
        (entity_type,),
    )
    key_values = keys["source_entity_key"].tolist()
    if default_key in key_values:
        key_index = key_values.index(default_key)
    else:
        key_index = 0
    entity_key = default_key if embedded and default_key else st.selectbox(
        "Entity key", key_values[:5000], index=min(key_index, len(key_values[:5000]) - 1)
    )
    revisions = frame(
        connection,
        """SELECT source_entity_revision_id, content_sha256,
                  source_last_updated_raw, source_last_updated_utc,
                  parser_version, created_at, normalized_content_json,
                  raw_content
           FROM source_entity_revisions
           WHERE source_entity_type=? AND source_entity_key=?
           ORDER BY created_at DESC""",
        (entity_type, entity_key),
    )
    observations = frame(
        connection,
        """SELECT source_entity_observation_id, collection_run_id,
                  source_entity_revision_id, observed_at
           FROM source_entity_observations
           JOIN source_entity_revisions USING (source_entity_revision_id)
           WHERE source_entity_type=? AND source_entity_key=?
           ORDER BY observed_at DESC""",
        (entity_type, entity_key),
    )
    st.markdown(f"**{len(revisions)} unique content revision(s); {len(observations)} observation(s)**")
    st.dataframe(observations, hide_index=True, width="stretch")
    revision_ids = revisions["source_entity_revision_id"].tolist()
    if revision_ids:
        selected_revision = st.selectbox(
            "Revision",
            revision_ids,
            key=f"revision_{'embedded' if embedded else 'global'}_{entity_type}",
        )
        selected = revisions[revisions["source_entity_revision_id"] == selected_revision].iloc[0]
        metadata = selected.drop(labels=["normalized_content_json", "raw_content"]).to_dict()
        st.dataframe(pd.DataFrame([metadata]), hide_index=True, width="stretch")
        left, right = st.columns(2)
        with left:
            st.markdown("##### Normalized content")
            st.json(pretty_json(selected["normalized_content_json"]))
        with right:
            st.markdown("##### Raw entity fragment")
            st.json(pretty_json(selected["raw_content"]))


def render_schema(connection):
    st.subheader("SQLite schema explorer")
    tables = frame(
        connection,
        """SELECT name AS table_name, sql
           FROM sqlite_master
           WHERE type='table' AND name NOT LIKE 'sqlite_%'
           ORDER BY name""",
    )
    table_counts = []
    for table_name in tables["table_name"]:
        try:
            count = scalar(connection, f'SELECT COUNT(*) FROM "{table_name}"')
        except sqlite3.Error:
            count = None
        table_counts.append({"table_name": table_name, "rows": count})
    counts = pd.DataFrame(table_counts)
    source_filter = st.multiselect(
        "Table groups",
        ["ingestion", "ocpi", "datex", "canonical", "legacy", "simulation"],
        default=["ingestion", "ocpi", "datex", "canonical"],
    )

    def group(name):
        if name.startswith("ocpi_"):
            return "ocpi"
        if name.startswith("datex_"):
            return "datex"
        if name.startswith("charging_"):
            return "canonical"
        if name.startswith("simulation_"):
            return "simulation"
        if name in {"data_sources", "source_endpoints", "collection_runs", "collection_pages",
                    "raw_payloads", "data_quality_issues", "source_entity_revisions",
                    "source_entity_observations"}:
            return "ingestion"
        return "legacy"

    counts["group"] = counts["table_name"].map(group)
    filtered = counts[counts["group"].isin(source_filter)]
    st.dataframe(filtered.sort_values(["group", "table_name"]), hide_index=True, width="stretch")
    if not filtered.empty:
        chart_data = filtered.sort_values("rows", ascending=False).head(30)
        st.plotly_chart(px.bar(chart_data, x="table_name", y="rows", color="group",
                               title="Largest selected tables"), width="stretch")

    table_name = st.selectbox("Inspect table", filtered["table_name"].tolist()) if not filtered.empty else None
    if table_name:
        columns = frame(connection, f'PRAGMA table_info("{table_name}")')
        foreign_keys = frame(connection, f'PRAGMA foreign_key_list("{table_name}")')
        indexes = frame(connection, f'PRAGMA index_list("{table_name}")')
        table_sql = tables.loc[tables["table_name"] == table_name, "sql"].iloc[0]
        column_tab, relation_tab, sample_tab, sql_tab = st.tabs(
            ["Columns", "Foreign keys & indexes", "Sample rows", "CREATE SQL"]
        )
        with column_tab:
            st.dataframe(columns, hide_index=True, width="stretch")
        with relation_tab:
            st.markdown("##### Foreign keys")
            st.dataframe(foreign_keys, hide_index=True, width="stretch")
            st.markdown("##### Indexes")
            st.dataframe(indexes, hide_index=True, width="stretch")
        with sample_tab:
            st.dataframe(frame(connection, f'SELECT * FROM "{table_name}" LIMIT 100'),
                         hide_index=True, width="stretch")
        with sql_tab:
            st.code(table_sql, language="sql")

    st.markdown("#### Core source-to-canonical topology")
    topology = go.Figure(
        go.Sankey(
            node=dict(
                label=[
                    "OCPI locations", "OCPI EVSEs", "OCPI connectors",
                    "DATEX sites/stations", "DATEX refill points", "DATEX connectors",
                    "Canonical sites", "Canonical equipment", "Status observations",
                ],
                color=["#3b82f6"] * 3 + ["#f59e0b"] * 3 + ["#8b5cf6"] * 2 + ["#64748b"],
            ),
            link=dict(
                source=[0, 1, 3, 4, 0, 3, 1, 4, 2, 5],
                target=[1, 2, 4, 5, 6, 6, 7, 7, 8, 8],
                value=[1] * 10,
                label=[
                    "contains", "contains", "contains", "contains",
                    "explicit site mapping", "explicit site mapping",
                    "explicit equipment mapping", "explicit equipment mapping",
                    "OCPI observations", "DATEX observations",
                ],
            ),
        )
    )
    topology.update_layout(height=440, margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(topology, width="stretch")
    st.caption("Topology illustrates table relationships, not record quantities or model causality.")


def render_dashboard_body():
    if not DATABASE_PATH.exists():
        st.error(f"Database not found: {DATABASE_PATH}")
        return
    try:
        connection = open_read_connection()
    except sqlite3.Error as error:
        st.error(f"Cannot open database: {error}")
        return
    try:
        if not table_exists(connection, "collection_runs"):
            st.error(
                "Database v2 tables are not initialized. Run `python src/collect.py --once` "
                "or initialize the v2 schema before opening this dashboard."
            )
            return
        total_runs = scalar(connection, "SELECT COUNT(*) FROM collection_runs")
        if total_runs == 0:
            render_empty_state(connection)
            return
        latest = render_header(connection)
        tabs = st.tabs([
            "Overview",
            "OCPI",
            "DATEX static",
            "DATEX dynamic",
            "Relationships",
            "Quality",
            "Revisions & raw",
            "Schema",
        ])
        with tabs[0]:
            render_overview(connection, latest)
        with tabs[1]:
            render_ocpi(connection)
        with tabs[2]:
            render_datex_static(connection)
        with tabs[3]:
            render_datex_dynamic(connection)
        with tabs[4]:
            render_relationships(connection)
        with tabs[5]:
            render_quality(connection)
        with tabs[6]:
            render_entity_revision_explorer(connection)
        with tabs[7]:
            render_schema(connection)
    except (sqlite3.Error, pd.errors.DatabaseError) as error:
        st.error(f"Database query failed: {error}")
    finally:
        connection.close()


if hasattr(st, "fragment"):
    st.fragment(run_every=f"{REFRESH_SECONDS}s")(render_dashboard_body)()
else:
    render_dashboard_body()
