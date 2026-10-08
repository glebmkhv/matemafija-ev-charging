"""Assumption-driven response for the available -> charging proxy channel."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Iterable

try:
    from .simulation_contract import (
        AssumptionDrivenResponseSpecification, PolicyIndependentResponseContract,
        ProvenanceClass, ResponseDriverContract, ResponseDriverPoint,
        ResponseMonotonicity, ResponseParameterDefinition,
    )
    from .transition_model import TransitionHazardEstimate
except ImportError:  # pragma: no cover
    from simulation_contract import (
        AssumptionDrivenResponseSpecification, PolicyIndependentResponseContract,
        ProvenanceClass, ResponseDriverContract, ResponseDriverPoint,
        ResponseMonotonicity, ResponseParameterDefinition,
    )
    from transition_model import TransitionHazardEstimate


ARRIVAL_RESPONSE_VERSION = "1.0.0"
ARRIVAL_CONTRACT_ID = "charging-start-hazard-exponential-shift"
ARRIVAL_PARAMETER_NAME = "theta_arrival"
ARRIVAL_DRIVER_NAME = "effective_policy_adjustment"
ARRIVAL_DRIVER_UNIT = "EUR/min"


@dataclass(frozen=True)
class ArrivalResponseResult:
    entity_id: str
    evaluation_time_utc: datetime
    driver_time_utc: datetime
    driver_value: float
    driver_unit: str
    response_delay_minutes: int
    theta_arrival: float
    theta_arrival_unit: str
    baseline_hazard_per_hour: float
    hazard_multiplier: float
    adjusted_hazard_per_hour: float
    decision_interval_minutes: int
    baseline_start_probability: float
    adjusted_start_probability: float
    response_model_id: str
    response_model_version: str
    response_contract_id: str = ARRIVAL_CONTRACT_ID
    response_contract_version: str = ARRIVAL_RESPONSE_VERSION
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED

    def validate(self):
        if self.evaluation_time_utc.tzinfo is None or self.driver_time_utc.tzinfo is None:
            raise ValueError("Arrival response timestamps must include timezones")
        cutoff = self.evaluation_time_utc - timedelta(
            minutes=self.response_delay_minutes
        )
        if self.driver_time_utc > cutoff:
            raise ValueError("Arrival response driver violates the declared delay")
        values = (
            self.driver_value, self.theta_arrival, self.baseline_hazard_per_hour,
            self.hazard_multiplier, self.adjusted_hazard_per_hour,
            self.baseline_start_probability, self.adjusted_start_probability,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Arrival response values must be finite")
        if min(
            self.theta_arrival, self.baseline_hazard_per_hour,
            self.hazard_multiplier, self.adjusted_hazard_per_hour,
        ) < 0:
            raise ValueError("Arrival sensitivity and hazards cannot be negative")
        if not 0 <= self.baseline_start_probability <= 1:
            raise ValueError("Baseline start probability must be in [0, 1]")
        if not 0 <= self.adjusted_start_probability <= 1:
            raise ValueError("Adjusted start probability must be in [0, 1]")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Arrival response must have simulated provenance")
        if (self.driver_unit != ARRIVAL_DRIVER_UNIT
                or self.theta_arrival_unit != "min/EUR"
                or not self.response_model_id or not self.response_model_version):
            raise ValueError("Arrival response identity or units are invalid")


def arrival_response_contract():
    return PolicyIndependentResponseContract(
        contract_id=ARRIVAL_CONTRACT_ID,
        contract_version=ARRIVAL_RESPONSE_VERSION,
        channel_id="charging_start_proxy",
        source_status="available",
        destination_status="charging",
        baseline_input_name="charging_start_hazard_per_hour",
        baseline_input_unit="1/hour",
        response_output_name="adjusted_charging_start_hazard_per_hour",
        response_output_unit="1/hour",
        driver=ResponseDriverContract(
            name=ARRIVAL_DRIVER_NAME, unit=ARRIVAL_DRIVER_UNIT,
        ),
        functional_form=(
            "adjusted_hazard = baseline_hazard * "
            "exp(-theta_arrival * delayed_driver)"
        ),
        parameter_definitions=(ResponseParameterDefinition(
            name=ARRIVAL_PARAMETER_NAME, unit="min/EUR", lower_bound=0.0,
        ),),
        monotonicity=ResponseMonotonicity.NONINCREASING,
        supported_simulated_outcomes=(
            "adjusted_charging_start_hazard_per_hour",
            "adjusted_charging_start_probability",
            "simulated_charging_start_transition",
            "deferred_or_displaced_start_proxy",
        ),
    )


def arrival_response_specification(theta_arrival, *, delay_minutes=0):
    specification = AssumptionDrivenResponseSpecification(
        model_id="assumed-arrival-response",
        model_version=ARRIVAL_RESPONSE_VERSION,
        contract=arrival_response_contract(),
        parameters={ARRIVAL_PARAMETER_NAME: theta_arrival},
        supported_simulated_outcomes=(
            "adjusted_charging_start_hazard_per_hour",
            "adjusted_charging_start_probability",
            "deferred_or_displaced_start_proxy",
        ),
        delay_minutes=delay_minutes,
    )
    specification.validate()
    return specification


def apply_arrival_response(
    baseline: TransitionHazardEstimate,
    driver_points: Iterable[ResponseDriverPoint],
    specification: AssumptionDrivenResponseSpecification,
    *,
    entity_id: str,
    evaluation_time_utc: datetime,
):
    """Adjust the accepted charging-start proxy; do not infer total arrivals."""
    if evaluation_time_utc.tzinfo is None:
        raise ValueError("Arrival response evaluation time must include a timezone")
    contract = arrival_response_contract()
    specification.validate()
    if specification.contract != contract:
        raise ValueError("Arrival response requires the canonical arrival contract")
    if (baseline.channel != "charging_start_proxy"
            or baseline.source_status != "available"
            or baseline.destination_status != "charging"):
        raise ValueError("Arrival response requires an available-to-charging baseline")
    if not baseline.locally_qualified or baseline.hazard_per_hour is None:
        raise ValueError("Arrival response requires a qualified baseline hazard")
    if baseline.hazard_per_hour < 0:
        raise ValueError("Baseline charging-start hazard cannot be negative")

    cutoff = evaluation_time_utc - timedelta(minutes=specification.delay_minutes)
    candidates = []
    seen = set()
    for point in driver_points:
        if point.entity_id != entity_id:
            continue
        if point.effective_at_utc.tzinfo is None:
            raise ValueError("Response driver timestamp must include a timezone")
        if point.effective_at_utc > cutoff:
            continue
        point.validate(contract)
        if point.effective_at_utc in seen:
            raise ValueError("Duplicate response driver time for one entity")
        seen.add(point.effective_at_utc)
        candidates.append(point)
    if not candidates:
        raise ValueError("No response driver is available at the delayed evaluation time")
    driver = max(candidates, key=lambda item: item.effective_at_utc)
    theta = specification.parameters[ARRIVAL_PARAMETER_NAME]
    exponent = -theta * driver.value
    if not -700 <= exponent <= 700:
        raise ValueError("Arrival response exponent is outside numerical safety bounds")
    multiplier = math.exp(exponent)
    adjusted_hazard = baseline.hazard_per_hour * multiplier
    interval_hours = baseline.decision_interval_minutes / 60
    q0 = 1 - math.exp(-baseline.hazard_per_hour * interval_hours)
    q1 = 1 - math.exp(-adjusted_hazard * interval_hours)
    result = ArrivalResponseResult(
        entity_id=entity_id,
        evaluation_time_utc=evaluation_time_utc,
        driver_time_utc=driver.effective_at_utc,
        driver_value=driver.value,
        driver_unit=driver.driver_unit,
        response_delay_minutes=specification.delay_minutes,
        theta_arrival=theta,
        theta_arrival_unit="min/EUR",
        baseline_hazard_per_hour=baseline.hazard_per_hour,
        hazard_multiplier=multiplier,
        adjusted_hazard_per_hour=adjusted_hazard,
        decision_interval_minutes=baseline.decision_interval_minutes,
        baseline_start_probability=q0,
        adjusted_start_probability=q1,
        response_model_id=specification.model_id,
        response_model_version=specification.model_version,
    )
    result.validate()
    return result
