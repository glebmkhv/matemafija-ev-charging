"""Live read-only dashboard for the Matemafija OCPI SQLite database."""

from datetime import datetime, timezone
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

from database import DATABASE_PATH


REFRESH_SECONDS = 30
STATUS_COLORS = {
    "AVAILABLE": "#16a34a",
    "CHARGING": "#2563eb",
    "INOPERATIVE": "#f59e0b",
    "OUTOFORDER": "#dc2626",
    "UNKNOWN": "#64748b",
    "REMOVED": "#334155",
}


st.set_page_config(
    page_title="Matemafija EV Network Monitor",
    page_icon="⚡",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
    [data-testid="stMetric"] {
        background: #0f172a;
        border: 1px solid #263449;
        border-radius: 12px;
        padding: 14px 16px;
    }
    [data-testid="stMetricLabel"] {color: #94a3b8;}
    [data-testid="stMetricValue"] {color: #f8fafc;}
    .monitor-subtitle {color: #94a3b8; margin-top: -0.7rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def open_read_connection():
    """Open SQLite in read-only mode while the collector may be writing."""
    uri = f"file:{DATABASE_PATH}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def read_frame(connection, query, parameters=()):
    """Return a SQL query as a pandas DataFrame."""
    return pd.read_sql_query(query, connection, params=parameters)


def load_dashboard_data():
    """Read one consistent dashboard view from the latest saved snapshot."""
    connection = open_read_connection()
    try:
        latest_row = connection.execute(
            "SELECT MAX(collected_at) FROM status_history"
        ).fetchone()
        latest_at = latest_row[0]
        if latest_at is None:
            return None

        statuses = read_frame(
            connection,
            """
            SELECT current_status AS status, COUNT(*) AS evse_count
            FROM evses
            WHERE last_seen_at = ?
            GROUP BY current_status
            ORDER BY evse_count DESC
            """,
            (latest_at,),
        )
        locations = read_frame(
            connection,
            """
            SELECT
                l.location_id,
                l.name,
                l.city,
                l.operator_name,
                l.latitude,
                l.longitude,
                COUNT(e.evse_id) AS evse_count,
                SUM(CASE WHEN e.current_status = 'AVAILABLE' THEN 1 ELSE 0 END)
                    AS available,
                SUM(CASE WHEN e.current_status = 'CHARGING' THEN 1 ELSE 0 END)
                    AS charging,
                SUM(CASE WHEN e.current_status IN ('INOPERATIVE', 'OUTOFORDER')
                    THEN 1 ELSE 0 END) AS unavailable
            FROM locations AS l
            LEFT JOIN evses AS e
                ON e.location_id = l.location_id
                AND e.last_seen_at = ?
            WHERE l.last_seen_at = ?
            GROUP BY
                l.location_id, l.name, l.city, l.operator_name,
                l.latitude, l.longitude
            """,
            (latest_at, latest_at),
        )
        timeline = read_frame(
            connection,
            """
            SELECT collected_at, status, COUNT(*) AS evse_count
            FROM status_history
            GROUP BY collected_at, status
            ORDER BY collected_at
            """,
        )
        connectors = read_frame(
            connection,
            """
            SELECT
                c.standard,
                c.power_type,
                c.max_electric_power_w / 1000.0 AS max_power_kw,
                COUNT(*) AS connector_count
            FROM connectors AS c
            JOIN evses AS e ON e.evse_id = c.evse_id
            WHERE e.last_seen_at = ?
            GROUP BY c.standard, c.power_type, c.max_electric_power_w
            """,
            (latest_at,),
        )
        tariff_components = read_frame(
            connection,
            """
            SELECT
                component_type,
                CAST(price AS REAL) AS price,
                step_size,
                vat
            FROM tariff_price_components
            """,
        )
        recent_runs = read_frame(
            connection,
            """
            SELECT
                collector_run_id,
                MIN(collected_at) AS collected_at,
                COUNT(*) AS observations,
                SUM(CASE WHEN status = 'AVAILABLE' THEN 1 ELSE 0 END)
                    AS available,
                SUM(CASE WHEN status = 'CHARGING' THEN 1 ELSE 0 END)
                    AS charging
            FROM status_history
            GROUP BY collector_run_id
            ORDER BY collected_at DESC
            LIMIT 20
            """,
        )
        changes = read_frame(
            connection,
            """
            SELECT entity_type, COUNT(*) AS version_count
            FROM entity_changes
            GROUP BY entity_type
            ORDER BY entity_type
            """,
        )
        counts = {
            "tariffs": connection.execute(
                "SELECT COUNT(*) FROM tariffs"
            ).fetchone()[0],
            "connectors": connection.execute(
                "SELECT COUNT(*) FROM connectors"
            ).fetchone()[0],
            "observations": connection.execute(
                "SELECT COUNT(*) FROM status_history"
            ).fetchone()[0],
            "unknown": connection.execute(
                """
                SELECT COUNT(*) FROM evses
                WHERE last_seen_at = ? AND current_status = 'UNKNOWN'
                """,
                (latest_at,),
            ).fetchone()[0],
            "missing_coordinates": connection.execute(
                """
                SELECT COUNT(*) FROM locations
                WHERE last_seen_at = ?
                    AND (latitude IS NULL OR longitude IS NULL)
                """,
                (latest_at,),
            ).fetchone()[0],
        }
    finally:
        connection.close()

    return {
        "latest_at": latest_at,
        "statuses": statuses,
        "locations": locations,
        "timeline": timeline,
        "connectors": connectors,
        "tariff_components": tariff_components,
        "recent_runs": recent_runs,
        "changes": changes,
        "counts": counts,
    }


def local_timestamp(value):
    """Format an ISO timestamp in the project's Vilnius time zone."""
    timestamp = pd.to_datetime(value, utc=True)
    return timestamp.tz_convert("Europe/Vilnius").strftime("%Y-%m-%d %H:%M:%S")


def status_value(statuses, status):
    rows = statuses.loc[statuses["status"] == status, "evse_count"]
    return int(rows.iloc[0]) if not rows.empty else 0


def render_dashboard():
    st.title("Vilnius EV network monitor")
    st.markdown(
        '<p class="monitor-subtitle">Observed public OCPI state and database health</p>',
        unsafe_allow_html=True,
    )

    if not DATABASE_PATH.exists():
        st.error(f"Database not found: {DATABASE_PATH}")
        return

    try:
        data = load_dashboard_data()
    except sqlite3.Error as error:
        st.error(f"Database is temporarily unavailable: {error}")
        return

    if data is None:
        st.info("The database contains no OCPI observations yet.")
        return

    latest_at = pd.to_datetime(data["latest_at"], utc=True)
    age_seconds = max(
        0,
        int((datetime.now(timezone.utc) - latest_at.to_pydatetime()).total_seconds()),
    )
    statuses = data["statuses"]
    locations = data["locations"]

    cities = sorted(
        city for city in locations["city"].dropna().unique() if city
    )
    default_city = cities.index("Vilnius") + 1 if "Vilnius" in cities else 0
    city_options = ["All cities", *cities]
    selected_city = st.sidebar.selectbox(
        "City",
        city_options,
        index=default_city,
    )
    operators = sorted(
        operator
        for operator in locations["operator_name"].dropna().unique()
        if operator
    )
    selected_operators = st.sidebar.multiselect(
        "Operators",
        operators,
    )
    st.sidebar.caption(f"Auto-refresh: {REFRESH_SECONDS} seconds")
    st.sidebar.caption(f"Database: {DATABASE_PATH.name}")

    filtered = locations.copy()
    if selected_city != "All cities":
        filtered = filtered[filtered["city"] == selected_city]
    if selected_operators:
        filtered = filtered[
            filtered["operator_name"].isin(selected_operators)
        ]

    total_evses = int(filtered["evse_count"].sum())
    available = int(filtered["available"].sum())
    charging = int(filtered["charging"].sum())
    availability_rate = 100 * available / total_evses if total_evses else 0

    metric_columns = st.columns(6)
    metric_columns[0].metric("Locations", f"{len(filtered):,}")
    metric_columns[1].metric("EVSEs", f"{total_evses:,}")
    metric_columns[2].metric("Available", f"{available:,}")
    metric_columns[3].metric("Charging", f"{charging:,}")
    metric_columns[4].metric("Availability", f"{availability_rate:.1f}%")
    metric_columns[5].metric("Snapshot age", f"{age_seconds // 60} min")

    st.caption(
        f"Latest complete snapshot: {local_timestamp(data['latest_at'])} "
        "Europe/Vilnius"
    )

    overview_tab, network_tab, history_tab, tariffs_tab, quality_tab = st.tabs(
        ["Overview", "Network", "History", "Tariffs", "Data quality"]
    )

    with overview_tab:
        left, right = st.columns([1, 2])
        with left:
            status_chart = px.pie(
                statuses,
                names="status",
                values="evse_count",
                hole=0.58,
                color="status",
                color_discrete_map=STATUS_COLORS,
                title="Current EVSE status",
            )
            status_chart.update_layout(
                legend_title_text="",
                margin=dict(l=10, r=10, t=50, b=10),
            )
            st.plotly_chart(status_chart, width="stretch")

        with right:
            map_data = filtered.dropna(subset=["latitude", "longitude"]).copy()
            if map_data.empty:
                st.info("No coordinates are available for this filter.")
            else:
                map_data["pressure"] = (
                    map_data["charging"] + map_data["unavailable"]
                ) / map_data["evse_count"].clip(lower=1)
                map_chart = px.scatter_map(
                    map_data,
                    lat="latitude",
                    lon="longitude",
                    color="pressure",
                    size="evse_count",
                    hover_name="name",
                    hover_data={
                        "operator_name": True,
                        "available": True,
                        "charging": True,
                        "evse_count": True,
                        "latitude": False,
                        "longitude": False,
                        "pressure": ":.2f",
                    },
                    color_continuous_scale="RdYlGn_r",
                    zoom=10 if selected_city != "All cities" else 6,
                    height=500,
                )
                map_chart.update_layout(
                    map_style="carto-positron",
                    margin=dict(l=0, r=0, t=40, b=0),
                    title="Observed network pressure",
                )
                st.plotly_chart(map_chart, width="stretch")

    with network_tab:
        st.subheader("Charging locations")
        display_locations = filtered[
            [
                "name",
                "city",
                "operator_name",
                "evse_count",
                "available",
                "charging",
                "unavailable",
            ]
        ].sort_values(["charging", "evse_count"], ascending=False)
        st.dataframe(
            display_locations,
            hide_index=True,
            width="stretch",
            column_config={
                "name": "Location",
                "operator_name": "Operator",
                "evse_count": st.column_config.NumberColumn("EVSEs"),
                "available": st.column_config.NumberColumn("Available"),
                "charging": st.column_config.NumberColumn("Charging"),
                "unavailable": st.column_config.NumberColumn("Unavailable"),
            },
        )

        st.subheader("Connector inventory")
        connector_summary = (
            data["connectors"]
            .groupby(["standard", "power_type"], dropna=False)["connector_count"]
            .sum()
            .reset_index()
        )
        connector_chart = px.bar(
            connector_summary,
            x="standard",
            y="connector_count",
            color="power_type",
            title="Connectors by standard and power type",
        )
        st.plotly_chart(connector_chart, width="stretch")

    with history_tab:
        timeline = data["timeline"].copy()
        timeline["collected_at"] = pd.to_datetime(
            timeline["collected_at"], utc=True
        ).dt.tz_convert("Europe/Vilnius")
        timeline_chart = px.line(
            timeline,
            x="collected_at",
            y="evse_count",
            color="status",
            markers=True,
            color_discrete_map=STATUS_COLORS,
            title="Observed status counts by collection cycle",
        )
        st.plotly_chart(timeline_chart, width="stretch")
        st.subheader("Recent collection cycles")
        recent_runs = data["recent_runs"].copy()
        recent_runs["collected_at"] = recent_runs["collected_at"].map(
            local_timestamp
        )
        st.dataframe(recent_runs, hide_index=True, width="stretch")

    with tariffs_tab:
        st.metric("Current tariffs", f"{data['counts']['tariffs']:,}")
        tariff_components = data["tariff_components"].copy()
        if tariff_components.empty:
            st.info("No tariff components have been collected.")
        else:
            type_counts = (
                tariff_components.groupby("component_type")
                .size()
                .rename("components")
                .reset_index()
            )
            left, right = st.columns(2)
            with left:
                component_chart = px.bar(
                    type_counts,
                    x="component_type",
                    y="components",
                    title="Tariff component types",
                )
                st.plotly_chart(component_chart, width="stretch")
            with right:
                positive_prices = tariff_components[
                    tariff_components["price"].between(0, 10)
                ]
                price_chart = px.box(
                    positive_prices,
                    x="component_type",
                    y="price",
                    points=False,
                    title="Price distributions up to 10 currency units",
                )
                st.plotly_chart(price_chart, width="stretch")
            st.caption(
                "Price units depend on component type; ENERGY, TIME and "
                "PARKING_TIME should not be interpreted as the same unit."
            )

    with quality_tab:
        quality_columns = st.columns(4)
        quality_columns[0].metric(
            "All observations",
            f"{data['counts']['observations']:,}",
        )
        quality_columns[1].metric(
            "Stored connectors",
            f"{data['counts']['connectors']:,}",
        )
        quality_columns[2].metric(
            "UNKNOWN status",
            f"{data['counts']['unknown']:,}",
        )
        quality_columns[3].metric(
            "Missing coordinates",
            f"{data['counts']['missing_coordinates']:,}",
        )
        changes_chart = px.bar(
            data["changes"],
            x="entity_type",
            y="version_count",
            title="Unique source versions retained in entity_changes",
        )
        st.plotly_chart(changes_chart, width="stretch")
        st.caption(
            "Current-state tables are updated in place. status_history "
            "appends every observation, while entity_changes appends only "
            "new source content."
        )


@st.fragment(run_every=REFRESH_SECONDS)
def live_fragment():
    render_dashboard()


live_fragment()
