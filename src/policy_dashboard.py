"""Read-only, claim-safe Policy Lab for the Hack4Vilnius presentation."""

import sqlite3

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

try:
    from .database_v2 import DATABASE_PATH
    from .policy_lab import load_policy_lab_evidence, policy_claims, response_curve
except ImportError:  # pragma: no cover
    try:
        from src.database_v2 import DATABASE_PATH
        from src.policy_lab import (
            load_policy_lab_evidence, policy_claims, response_curve,
        )
    except ImportError:
        from database_v2 import DATABASE_PATH
        from policy_lab import load_policy_lab_evidence, policy_claims, response_curve


st.set_page_config(
    page_title="Matemafija Policy Lab",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container {max-width: 1500px; padding-top: 1.4rem;}
[data-testid="stMetric"] {background:#101827;border:1px solid #26364e;
 border-radius:14px;padding:14px 16px;}
.evidence {border-left:4px solid #22c55e;background:#0d2019;padding:1rem;
 border-radius:0 10px 10px 0;}
.assumption {border-left:4px solid #f59e0b;background:#251b09;padding:1rem;
 border-radius:0 10px 10px 0;}
.boundary {border-left:4px solid #38bdf8;background:#0c1d2c;padding:1rem;
 border-radius:0 10px 10px 0;}
</style>
""", unsafe_allow_html=True)


def open_connection():
    try:
        connection = sqlite3.connect(
            f"file:{DATABASE_PATH}?mode=ro", uri=True, timeout=5,
        )
        connection.execute("SELECT 1")
        return connection
    except sqlite3.Error:
        return sqlite3.connect(
            f"file:{DATABASE_PATH}?immutable=1", uri=True, timeout=5,
        )


@st.cache_data(ttl=60)
def database_payload():
    connection = open_connection()
    try:
        evidence = load_policy_lab_evidence(connection)
        locations = pd.read_sql_query("""
            SELECT l.ocpi_location_key, l.name, l.city, l.latitude, l.longitude,
                   COUNT(CASE WHEN e.is_current=1 THEN 1 END) AS evse_count
            FROM ocpi_locations l
            LEFT JOIN ocpi_evses e USING (ocpi_location_key)
            WHERE l.is_current=1
            GROUP BY l.ocpi_location_key
            ORDER BY l.ocpi_location_key
        """, connection)
        statuses = pd.read_sql_query("""
            SELECT source_status_canonical AS status, COUNT(*) AS evse_count
            FROM ocpi_evses WHERE is_current=1
            GROUP BY source_status_canonical ORDER BY evse_count DESC
        """, connection)
        tariff_components = pd.read_sql_query("""
            SELECT pc.component_type, COUNT(*) AS component_count
            FROM ocpi_tariffs t
            JOIN ocpi_tariff_price_components pc
              ON pc.source_entity_revision_id=t.current_revision_id
            WHERE t.is_current=1
            GROUP BY pc.component_type ORDER BY component_count DESC
        """, connection)
        return evidence, locations, statuses, tariff_components
    finally:
        connection.close()


def evidence_tab(evidence, locations, statuses, tariff_components):
    st.subheader("1 · What the city data already supports")
    st.markdown(
        '<div class="evidence"><b>Observed layer.</b> Every value in this tab '
        'comes from the read-only OCPI/DATEX database. No behavioural response '
        'or queue is inferred.</div>', unsafe_allow_html=True,
    )
    columns = st.columns(4)
    columns[0].metric("OCPI status observations", f"{evidence.observation_count:,}")
    columns[1].metric("Current locations", f"{evidence.current_location_count:,}")
    columns[2].metric("Current tariffs", f"{evidence.current_tariff_count:,}")
    columns[3].metric("Tariff assignments", f"{evidence.current_tariff_assignment_count:,}")

    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("#### Spatial coverage")
        mapped = locations.dropna(subset=["latitude", "longitude"])
        if not mapped.empty:
            chart = px.scatter_map(
                mapped, lat="latitude", lon="longitude", size="evse_count",
                hover_name="name", hover_data=["city", "evse_count"],
                zoom=9, height=480, map_style="carto-positron",
            )
            chart.update_layout(margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(chart, width="stretch")
        st.caption(
            f"{evidence.coordinate_location_count:,} current locations have usable "
            "coordinates. Spatial redistribution remains scenario-conditional."
        )
    with right:
        st.markdown("#### Formal history gate")
        st.progress(evidence.history_progress)
        st.metric(
            "Collected history",
            f"{evidence.history_span_days:.2f} / {evidence.required_history_days:.0f} days",
        )
        if evidence.history_gate_possible:
            st.success(
                "The global history-duration prerequisite is met. Individual "
                "sites must still pass coverage, transition-count and F1 gates."
            )
        else:
            st.warning(
                "Counterfactual execution remains locked: the seven-day history "
                "prerequisite is not yet met. Collection should continue."
            )
        if not statuses.empty:
            st.plotly_chart(px.bar(
                statuses, x="status", y="evse_count", color="status",
                title="Current observed OCPI EVSE statuses",
            ), width="stretch")
        if not tariff_components.empty:
            st.plotly_chart(px.bar(
                tariff_components, x="component_type", y="component_count",
                title="Observed F1 tariff component structure",
            ), width="stretch")


def mechanism_tab():
    st.subheader("2 · Policy mechanism sandbox")
    st.markdown(
        '<div class="assumption"><b>Assumption layer.</b> Controls below explain '
        'the mathematical mechanism. They are not estimates of Vilnius driver '
        'elasticity and are not a forecast.</div>', unsafe_allow_html=True,
    )
    left, right = st.columns([.85, 1.6])
    with left:
        adjustment = st.slider("Maximum OSA adjustment · EUR/min", 0.0, .15, .05, .01)
        theta_release = st.slider("Assumed release sensitivity θᵣ · min/EUR", 0.0, 50.0, 10.0, 1.0)
        theta_arrival = st.slider("Assumed accepted-start sensitivity θₐ · min/EUR", 0.0, 50.0, 5.0, 1.0)
        baseline_release = st.slider("Illustrative baseline release probability", .01, .80, .20, .01)
        baseline_start = st.slider("Illustrative baseline start probability", .01, .80, .20, .01)
        st.markdown("""
        **OSA-v1** adds a bounded TIME component to the observed F1 tariff.

        - release: `h₁ = h₀ · exp(+θᵣ · λΔp)`
        - accepted start: `h₁ = h₀ · exp(−θₐ · λΔp)`
        """)
    intensities = tuple(index/20 for index in range(21))
    release = response_curve(
        baseline_release, theta_release, adjustment,
        direction="release", intensity_values=intensities,
    )
    start = response_curve(
        baseline_start, theta_arrival, adjustment,
        direction="start", intensity_values=intensities,
    )
    chart_data = pd.DataFrame((*release, *start))
    with right:
        chart = px.line(
            chart_data, x="lambda", y="probability", color="direction",
            markers=True, range_y=[0, 1],
            title="Mechanism response across rollout intensity λ",
            labels={"probability": "5-minute transition probability"},
        )
        st.plotly_chart(chart, width="stretch")
        st.caption(
            "Baseline probabilities in this sandbox are user-selected explanatory "
            "inputs. Formal runs replace them with qualified site/hour estimates."
        )


def robustness_tab(evidence):
    st.subheader("3 · Robustness decision rule")
    st.markdown(
        '<div class="boundary"><b>Conditional output.</b> A scenario becomes '
        'robust only when the lower 95% Wilson bound—not merely the observed '
        'success frequency—is at least 80%.</div>', unsafe_allow_html=True,
    )
    flow = go.Figure(go.Sankey(
        node=dict(label=[
            "Observed OCPI/DATEX", "F1 tariff", "OSA-v1", "Assumed response",
            "Paired Monte Carlo", "Same scarcity metrics", "Robustness region",
            "Pilot decision",
        ]),
        link=dict(
            source=[0, 0, 1, 2, 3, 4, 5, 6],
            target=[1, 2, 4, 3, 4, 5, 6, 7],
            value=[1]*8,
        ),
    ))
    flow.update_layout(height=420, margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(flow, width="stretch")
    if not evidence.history_gate_possible:
        st.warning(
            "No effectiveness heatmap is displayed yet: current data fail the "
            "necessary seven-day history gate. Showing coloured scenario results "
            "now would turn assumptions into apparent evidence."
        )
    else:
        st.info(
            "The duration prerequisite is met. Generate formal per-site readiness "
            "reports and versioned run artifacts before publishing a heatmap."
        )
    st.markdown("""
    The final map is indexed by `λ × θ_release × θ_arrival × delay` and must show:

    - paired scarcity change and its simulation interval;
    - probability of improvement and Wilson interval;
    - minimum tested response threshold;
    - deferred/displaced accepted-start proxy;
    - receiver scarcity created by spatial redistribution.
    """)


def pitch_tab():
    st.subheader("4 · City decision narrative")
    claims = policy_claims()
    st.markdown("### The problem")
    st.write(
        "Vilnius cannot evaluate adaptive charging prices from a single formula: "
        "the future behavioural response has not yet been observed."
    )
    st.markdown("### The product")
    st.success(
        "A policy stress-testing digital twin that keeps factual tariffs and "
        "observations separate from explicit behavioural assumptions."
    )
    cols = st.columns(3)
    with cols[0]:
        st.markdown("#### Supported now")
        for item in claims["supported_now"]:
            st.markdown(f"- {item}")
    with cols[1]:
        st.markdown("#### Not claimed")
        for item in claims["not_supported"]:
            st.markdown(f"- {item}")
    with cols[2]:
        st.markdown("#### City next action")
        for item in claims["city_next_action"]:
            st.markdown(f"- {item}")
    st.markdown("### One-sentence conclusion")
    st.markdown(
        '> **We do not claim that adaptive pricing is already proven; we identify '
        'the minimum behavioural response under which it becomes robust, expose '
        'the access and spatial trade-offs, and turn that threshold into a '
        'measurable city pilot.**'
    )


def main():
    st.title("Matemafija · EV Charging Policy Lab")
    st.caption("Hack4Vilnius · evidence → assumptions → simulation → decision")
    if not DATABASE_PATH.exists():
        st.error(f"Database not found: {DATABASE_PATH}")
        return
    try:
        evidence, locations, statuses, tariffs = database_payload()
    except (sqlite3.Error, pd.errors.DatabaseError, ValueError) as error:
        st.error(f"Cannot load Policy Lab evidence: {error}")
        return
    tabs = st.tabs([
        "Evidence", "Mechanism", "Robustness", "Decision narrative",
    ])
    with tabs[0]:
        evidence_tab(evidence, locations, statuses, tariffs)
    with tabs[1]:
        mechanism_tab()
    with tabs[2]:
        robustness_tab(evidence)
    with tabs[3]:
        pitch_tab()
    st.divider()
    st.caption(
        "Observed · reconstructed · estimated · policy-defined · assumed · "
        "simulated — provenance remains visible throughout the workflow."
    )


main()
