"""Read-only, claim-safe Policy Lab for the Hack4Vilnius presentation."""

import sqlite3

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

try:
    from .database_v2 import DATABASE_PATH
    from .policy_lab import (
        joint_gate_preview, load_policy_lab_evidence, policy_claims,
        policy_lab_flow, receiver_choice_curve, response_curve,
    )
except ImportError:  # pragma: no cover
    try:
        from src.database_v2 import DATABASE_PATH
        from src.policy_lab import (
            joint_gate_preview, load_policy_lab_evidence, policy_claims,
            policy_lab_flow, receiver_choice_curve, response_curve,
        )
    except ImportError:
        from database_v2 import DATABASE_PATH
        from policy_lab import (
            joint_gate_preview, load_policy_lab_evidence, policy_claims,
            policy_lab_flow, receiver_choice_curve, response_curve,
        )


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
.not-evaluable {border-left:4px solid #a78bfa;background:#1b1530;padding:1rem;
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
    st.subheader("2 · Contribution-to-credit policy")
    st.markdown(
        '<div class="boundary"><b>Policy-defined layer.</b> Scarcity evidence '
        'activates a bounded contribution signal; already funded MCU can support '
        'eligible alternative-site offers. An offer is not issuance.</div>',
        unsafe_allow_html=True,
    )
    flow = policy_lab_flow()
    st.plotly_chart(go.Figure(go.Sankey(
        node=dict(label=[f"{name}<br>{description}" for name, description in flow]),
        link=dict(
            source=list(range(len(flow)-1)),
            target=list(range(1, len(flow))), value=[1]*(len(flow)-1),
        ),
    )).update_layout(height=330, margin=dict(l=10, r=10, t=15, b=10)),
        width="stretch")
    left, middle, right = st.columns(3)
    with left:
        st.markdown("#### Origin")
        st.write("Observable sustained scarcity → bounded OSA signal.")
        st.code("contribution quote ≠ accrued contribution")
    with middle:
        st.markdown("#### Shared pool")
        st.write("Integer MCU with reserve, reservation, issuance and redemption states.")
        st.code("funded = available + reserved + outstanding + settled")
    with right:
        st.markdown("#### Receiver")
        st.write("Only funded, safety-passed alternatives enter choice.")
        st.code("offer → choice → reservation → simulated issuance")
    st.caption(
        "MATEMAFIJA MCU is a simulated policy accounting unit. It is not money, "
        "cashback already paid, or a DAEI unit."
    )


def response_tab():
    st.subheader("3 · Assumed behavioural response")
    st.markdown(
        '<div class="assumption"><b>Assumption layer.</b> These controls explain '
        'mechanisms and sensitivity. They are not fitted Vilnius elasticities or '
        'individual forecasts.</div>', unsafe_allow_html=True,
    )
    control, charts = st.columns([.9, 1.7])
    with control:
        adjustment = st.slider("Maximum OSA adjustment · EUR/min", 0.0, .15, .05, .01)
        theta_release = st.slider("Release sensitivity θᵣ · min/EUR", 0.0, 50.0, 10.0, 1.0)
        theta_arrival = st.slider("Accepted-start sensitivity θₐ · min/EUR", 0.0, 50.0, 5.0, 1.0)
        beta_credit = st.slider("Credit sensitivity βcredit · per MCU", 0.0, .5, .10, .01)
        beta_distance = st.slider("Distance sensitivity βdistance · per km", 0.0, 3.0, .7, .1)
        receiver_distance = st.slider("Illustrative receiver distance · km", .1, 5.0, 2.0, .1)
        baseline_release = st.slider("Baseline release probability", .01, .80, .20, .01)
        baseline_start = st.slider("Baseline start probability", .01, .80, .20, .01)
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
    choice_data = pd.DataFrame(receiver_choice_curve(
        tuple(range(0, 26)), beta_credit_per_mcu=beta_credit,
        beta_distance_per_km=beta_distance, distance_km=receiver_distance,
    ))
    with charts:
        chart = px.line(
            chart_data, x="lambda", y="probability", color="direction",
            markers=True, range_y=[0, 1],
            title="Mechanism response across rollout intensity λ",
            labels={"probability": "5-minute transition probability"},
        )
        st.plotly_chart(chart, width="stretch")
        choice = px.line(
            choice_data, x="credit_mcu", y="receiver_probability",
            range_y=[0, 1], markers=True,
            title="Illustrative receiver choice versus outside option",
            labels={"receiver_probability": "Receiver selection probability"},
        )
        st.plotly_chart(choice, width="stretch")
        st.caption(
            "Formal runs use qualified transition estimates, immutable funded offers "
            "and paired random draws. This chart is explanatory only."
        )


def evaluation_tab(evidence):
    st.subheader("4 · Four-domain evaluation")
    st.markdown(
        '<div class="not-evaluable"><b>No composite-score shortcut.</b> System '
        'improvement cannot erase redistribution, access-proxy or accounting '
        'failure. Missing evidence remains not_evaluable.</div>',
        unsafe_allow_html=True,
    )
    domains = (
        ("System", "Scarcity change, availability, release/start trade-off"),
        ("Redistribution", "Offer coverage, outside share, receiver capacity"),
        ("User proxy", "MCU and straight-line distance; not welfare"),
        ("Accounting", "Funding identity, reserve, issuance and reconciliation"),
    )
    for column, (name, description) in zip(st.columns(4), domains):
        with column:
            st.markdown(f"#### {name}")
            st.write(description)
    st.markdown("#### Evidence-dependent outputs")
    left, right = st.columns(2)
    with left:
        st.success("Available in formal runs: paired scarcity, selections, capacity and MCU ledger.")
    with right:
        st.warning("Not evaluable now: total session cost, travel time, welfare and demographic fairness.")
    if not evidence.history_gate_possible:
        st.info(
            "Effectiveness results remain locked until the global history gate and "
            "per-site readiness gates pass. The interface does not fabricate a heatmap."
        )


def robustness_tab(evidence):
    st.subheader("5 · Joint observable robustness")
    st.markdown(
        '<div class="boundary"><b>Conditional output.</b> A scenario becomes '
        'robust only when every observable domain gate passes, at least 20 valid '
        'replications exist, no more than 20% are non-evaluable, and the lower '
        '95% Wilson bound is at least 80%.</div>', unsafe_allow_html=True,
    )
    cols = st.columns(4)
    labels = ("System", "Redistribution", "User proxy", "Accounting")
    states = []
    for column, label in zip(cols, labels):
        with column:
            value = st.selectbox(
                label, ("pass", "fail", "not evaluable"),
                key=f"gate-{label}",
            )
            states.append({"pass": True, "fail": False, "not evaluable": None}[value])
    preview = joint_gate_preview(*states)
    if preview == "success":
        st.success("Replication status: success — scenario-level Wilson test is still required.")
    elif preview == "failure":
        st.error("Replication status: failure — another domain cannot compensate for it.")
    else:
        st.warning("Replication status: not_evaluable — it is not counted as success.")
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
    The scenario map is indexed by upstream and downstream assumptions and shows:

    - paired scarcity change and its simulation interval;
    - probability of improvement and Wilson interval;
    - minimum tested response threshold;
    - deferred/displaced accepted-start proxy;
    - receiver capacity and outside/unassigned outcomes;
    - ledger reconciliation and joint observable robustness.
    """)


def pitch_tab():
    st.subheader("6 · City decision narrative")
    claims = policy_claims()
    st.markdown("### The problem")
    st.write(
        "Vilnius cannot evaluate adaptive charging prices from a single formula: "
        "the future behavioural response has not yet been observed."
    )
    st.markdown("### The product")
    st.success(
        "A policy stress-testing digital twin that turns qualified scarcity into "
        "balanced contribution-to-credit scenarios while keeping evidence, policy "
        "and behavioural assumptions separate."
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
        'the joint price-and-credit response conditions under which the policy is '
        'robust within observable limits, expose its spatial, access-proxy and '
        'accounting trade-offs, and turn them into a measurable city pilot.**'
    )
    st.info(
        "DAEI is a Lithuanian precedent and possible future integration path, not "
        "the current MCU mechanism and not part of the present computation graph."
    )


def main():
    st.title("Matemafija · EV Charging Policy Lab")
    st.caption(
        "Hack4Vilnius · evidence → policy → assumed response → paired simulation "
        "→ four-domain evaluation → decision"
    )
    if not DATABASE_PATH.exists():
        st.error(f"Database not found: {DATABASE_PATH}")
        return
    try:
        evidence, locations, statuses, tariffs = database_payload()
    except (sqlite3.Error, pd.errors.DatabaseError, ValueError) as error:
        st.error(f"Cannot load Policy Lab evidence: {error}")
        return
    tabs = st.tabs([
        "Evidence", "Policy", "Response", "Evaluation", "Robustness", "Decision",
    ])
    with tabs[0]:
        evidence_tab(evidence, locations, statuses, tariffs)
    with tabs[1]:
        mechanism_tab()
    with tabs[2]:
        response_tab()
    with tabs[3]:
        evaluation_tab(evidence)
    with tabs[4]:
        robustness_tab(evidence)
    with tabs[5]:
        pitch_tab()
    st.divider()
    st.caption(
        "Observed · reconstructed · estimated · policy-defined · assumed · "
        "simulated — provenance remains visible throughout the workflow."
    )


main()
