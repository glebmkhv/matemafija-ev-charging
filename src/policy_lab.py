"""Pure presentation helpers for the read-only policy stress-testing UI."""

from dataclasses import dataclass
from datetime import datetime
import math


POLICY_LAB_VERSION = "2.0.0"
REQUIRED_HISTORY_DAYS = 7.0


@dataclass(frozen=True)
class PolicyLabEvidenceSummary:
    observation_count: int
    first_observation_utc: datetime | None
    last_observation_utc: datetime | None
    history_span_days: float
    current_location_count: int
    current_tariff_count: int
    current_tariff_assignment_count: int
    coordinate_location_count: int
    history_gate_possible: bool
    required_history_days: float = REQUIRED_HISTORY_DAYS
    version: str = POLICY_LAB_VERSION

    @property
    def history_progress(self):
        return min(1.0, self.history_span_days / self.required_history_days)

    def validate(self):
        counts = (
            self.observation_count, self.current_location_count,
            self.current_tariff_count, self.current_tariff_assignment_count,
            self.coordinate_location_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("Policy Lab evidence counts cannot be negative")
        if self.history_span_days < 0 or self.required_history_days <= 0:
            raise ValueError("Policy Lab history spans are invalid")
        if (self.first_observation_utc is None) != (self.last_observation_utc is None):
            raise ValueError("Observation boundaries must be jointly present or absent")
        expected = self.history_span_days >= self.required_history_days
        if self.history_gate_possible != expected:
            raise ValueError("History gate screening flag is inconsistent")


def load_policy_lab_evidence(connection):
    row = connection.execute("""
        SELECT COUNT(*), MIN(observed_at), MAX(observed_at)
        FROM ocpi_evse_status_observations
    """).fetchone()
    first = _aware_datetime(row[1]) if row[1] else None
    last = _aware_datetime(row[2]) if row[2] else None
    span = (last-first).total_seconds()/86400 if first and last else 0.0
    result = PolicyLabEvidenceSummary(
        observation_count=row[0],
        first_observation_utc=first,
        last_observation_utc=last,
        history_span_days=span,
        current_location_count=_count(
            connection, "ocpi_locations", "is_current=1",
        ),
        current_tariff_count=_count(
            connection, "ocpi_tariffs", "is_current=1",
        ),
        current_tariff_assignment_count=_count(
            connection, "ocpi_connector_tariff_assignments", "is_current=1",
        ),
        coordinate_location_count=_count(
            connection, "ocpi_locations",
            "is_current=1 AND latitude IS NOT NULL AND longitude IS NOT NULL",
        ),
        history_gate_possible=span >= REQUIRED_HISTORY_DAYS,
    )
    result.validate()
    return result


def response_curve(
    baseline_probability,
    theta,
    maximum_adjustment_eur_per_min,
    *,
    direction,
    intensity_values,
    decision_interval_minutes=5,
):
    """Return a mechanism curve; values are assumptions, not fitted effects."""
    numeric = (
        baseline_probability, theta, maximum_adjustment_eur_per_min,
        decision_interval_minutes,
    )
    if any(isinstance(value, bool) or not math.isfinite(value) for value in numeric):
        raise ValueError("Response curve parameters must be finite")
    if not 0 <= baseline_probability < 1 or theta < 0:
        raise ValueError("Baseline probability or sensitivity is invalid")
    if maximum_adjustment_eur_per_min < 0 or decision_interval_minutes <= 0:
        raise ValueError("Adjustment and interval must be non-negative/positive")
    if direction not in {"release", "start"}:
        raise ValueError("Response direction must be release or start")
    interval_hours = decision_interval_minutes/60
    baseline_hazard = -math.log(1-baseline_probability)/interval_hours
    result = []
    for intensity in intensity_values:
        if (isinstance(intensity, bool) or not math.isfinite(intensity)
                or not 0 <= intensity <= 1):
            raise ValueError("Policy intensity must be in [0, 1]")
        driver = intensity*maximum_adjustment_eur_per_min
        sign = 1 if direction == "release" else -1
        exponent = sign*theta*driver
        if not -700 <= exponent <= 700:
            raise ValueError("Response exponent is outside numerical safety bounds")
        adjusted_hazard = baseline_hazard*math.exp(exponent)
        probability = 1-math.exp(-adjusted_hazard*interval_hours)
        result.append({
            "lambda": intensity,
            "effective_adjustment_eur_per_min": driver,
            "probability": probability,
            "direction": direction,
        })
    return tuple(result)


def receiver_choice_curve(
    credit_values_mcu,
    *,
    beta_credit_per_mcu,
    beta_distance_per_km,
    distance_km,
):
    """Illustrate receiver-vs-outside choice without implying fitted behaviour."""
    numeric = (beta_credit_per_mcu, beta_distance_per_km, distance_km)
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) or value < 0
        for value in numeric
    ):
        raise ValueError("Receiver-choice parameters must be finite and non-negative")
    rows = []
    for credit in credit_values_mcu:
        if (isinstance(credit, bool) or not isinstance(credit, (int, float))
                or not math.isfinite(credit) or credit < 0):
            raise ValueError("Illustrative credit values must be non-negative")
        utility = beta_credit_per_mcu*credit-beta_distance_per_km*distance_km
        if not -700 <= utility <= 700:
            raise ValueError("Receiver-choice utility is outside numerical bounds")
        receiver_probability = 1/(1+math.exp(-utility))
        rows.append({
            "credit_mcu": credit,
            "distance_km": distance_km,
            "receiver_probability": receiver_probability,
            "outside_probability": 1-receiver_probability,
        })
    return tuple(rows)


def illustrative_release_preview(
    *,
    baseline_probability=.20,
    maximum_adjustment_eur_per_min=.05,
    intensity_values=(0, .25, .5, .75, 1),
    sensitivity_values=(0, 5, 10, 20, 35),
):
    """Return an explanatory response surface, never an effectiveness estimate.

    The surface is intentionally independent of collected-history readiness.  It
    visualises the declared release-response equation so a presentation can show
    what an assumption-driven scenario means without publishing a formal scarcity
    heatmap before the transition model is data-qualified.
    """
    rows = []
    for theta in sensitivity_values:
        curve = response_curve(
            baseline_probability,
            theta,
            maximum_adjustment_eur_per_min,
            direction="release",
            intensity_values=intensity_values,
        )
        for point in curve:
            rows.append({
                "lambda": point["lambda"],
                "theta_release": theta,
                "release_probability_change_pp":
                    100*(point["probability"]-baseline_probability),
                "provenance": "assumed",
                "claim_scope": "illustrative_mechanism_only",
            })
    return tuple(rows)


def policy_lab_flow():
    """Return the fixed jury-facing story without embedding simulation results."""
    return (
        ("Evidence", "Observed OCPI/DATEX states and F1 tariff"),
        ("Policy", "OSA scarcity contribution and funded MCU alternatives"),
        ("Response", "Assumed release, start and receiver-choice mechanisms"),
        ("Simulation", "Paired common-random-number trajectories and ledger"),
        ("Evaluation", "System, redistribution, user-proxy and accounting"),
        ("Decision", "Joint observable robustness and measurable pilot"),
    )


def joint_gate_preview(system, redistribution, user_proxy, accounting):
    """Explain conjunctive status; None remains non-evaluable."""
    gates = (system, redistribution, user_proxy, accounting)
    if any(value not in (True, False, None) for value in gates):
        raise ValueError("Policy Lab gates must be true, false or unavailable")
    if any(value is False for value in gates):
        return "failure"
    if any(value is None for value in gates):
        return "not_evaluable"
    return "success"


def policy_claims():
    return {
        "supported_now": (
            "Observed OCPI/DATEX coverage and factual tariff structure",
            "Observable scarcity without claiming a physical queue",
            "Reproducible OSA, MCU ledger and explicit response assumptions",
            "Scenario-conditional observable robustness after all domain gates pass",
        ),
        "not_supported": (
            "Observed price elasticity of Vilnius drivers",
            "Causal queue or waiting-time reduction",
            "Observed post-charge idle time",
            "Guaranteed welfare, demographic fairness or mobility effect",
            "Equivalence between MATEMAFIJA MCU and regulated DAEI units",
        ),
        "city_next_action": (
            "Continue collection through the formal readiness window",
            "Agree operator roles, funding and credit acceptance rules",
            "Run a bounded pilot on selected sites",
            "Measure sessions, choices, redemption and displaced use",
            "Replace assumed response parameters with validated estimates",
        ),
    }


def _count(connection, table, condition):
    return connection.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {condition}"
    ).fetchone()[0]


def _aware_datetime(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Policy Lab accepts only timezone-aware observations")
    return parsed
