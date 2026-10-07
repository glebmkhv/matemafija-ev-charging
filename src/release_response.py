"""Assumption-driven response for the charging -> available proxy channel."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import math
from typing import Iterable

try:
    from .simulation_contract import (
        AssumptionDrivenResponseSpecification,
        PolicyIndependentResponseContract,
        ProvenanceClass,
        ResponseDriverContract,
        ResponseDriverPoint,
        ResponseMonotonicity,
        ResponseParameterDefinition,
    )
    from .transition_model import TransitionHazardEstimate
except ImportError:  # pragma: no cover
    from simulation_contract import (
        AssumptionDrivenResponseSpecification,
        PolicyIndependentResponseContract,
        ProvenanceClass,
        ResponseDriverContract,
        ResponseDriverPoint,
        ResponseMonotonicity,
        ResponseParameterDefinition,
    )
    from transition_model import TransitionHazardEstimate


RELEASE_RESPONSE_VERSION = "1.0.0"
RELEASE_CONTRACT_ID = "release-hazard-exponential-shift"
RELEASE_DRIVER_NAME = "effective_policy_adjustment"
RELEASE_DRIVER_UNIT = "EUR/min"
RELEASE_PARAMETER_NAME = "theta_release"


@dataclass(frozen=True)
class ReleaseResponseResult:
    entity_id: str
    evaluation_time_utc: datetime
    driver_time_utc: datetime
    driver_value: float
    driver_unit: str
    response_delay_minutes: int
    theta_release: float
    theta_release_unit: str
    baseline_hazard_per_hour: float
    hazard_multiplier: float
    adjusted_hazard_per_hour: float
    decision_interval_minutes: int
    baseline_release_probability: float
    adjusted_release_probability: float
    response_contract_id: str
    response_contract_version: str
    response_model_id: str
    response_model_version: str
    provenance: ProvenanceClass = ProvenanceClass.SIMULATED

    def validate(self):
        if self.evaluation_time_utc.tzinfo is None or self.driver_time_utc.tzinfo is None:
            raise ValueError("Release response timestamps must include timezones")
        if self.driver_time_utc > self.evaluation_time_utc:
            raise ValueError("Release response cannot use a future driver")
        if self.driver_time_utc > self.evaluation_time_utc - timedelta(
            minutes=self.response_delay_minutes
        ):
            raise ValueError("Release response driver violates the declared delay")
        numeric = (
            self.driver_value, self.theta_release, self.baseline_hazard_per_hour,
            self.hazard_multiplier, self.adjusted_hazard_per_hour,
            self.baseline_release_probability, self.adjusted_release_probability,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("Release response values must be finite")
        if min(self.baseline_hazard_per_hour, self.hazard_multiplier,
               self.adjusted_hazard_per_hour) < 0:
            raise ValueError("Release hazards and multiplier cannot be negative")
        if not 0 <= self.baseline_release_probability <= 1:
            raise ValueError("Baseline release probability must be in [0, 1]")
        if not 0 <= self.adjusted_release_probability <= 1:
            raise ValueError("Adjusted release probability must be in [0, 1]")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Adjusted release response must be simulated")

    def as_record(self):
        result = asdict(self)
        result["evaluation_time_utc"] = self.evaluation_time_utc.isoformat()
        result["driver_time_utc"] = self.driver_time_utc.isoformat()
        result["provenance"] = self.provenance.value
        return result


def release_response_contract():
    """Return the sole approved response contract for project step 8."""
    return PolicyIndependentResponseContract(
        contract_id=RELEASE_CONTRACT_ID,
        contract_version=RELEASE_RESPONSE_VERSION,
        channel_id="release_proxy",
        source_status="charging",
        destination_status="available",
        baseline_input_name="release_hazard_per_hour",
        baseline_input_unit="1/hour",
        response_output_name="adjusted_release_hazard_per_hour",
        response_output_unit="1/hour",
        driver=ResponseDriverContract(
            name=RELEASE_DRIVER_NAME,
            unit=RELEASE_DRIVER_UNIT,
        ),
        functional_form=(
            "adjusted_hazard = baseline_hazard * "
            "exp(theta_release * delayed_driver)"
        ),
        parameter_definitions=(ResponseParameterDefinition(
            name=RELEASE_PARAMETER_NAME,
            unit="min/EUR",
            lower_bound=0.0,
        ),),
        monotonicity=ResponseMonotonicity.NONDECREASING,
        supported_simulated_outcomes=(
            "adjusted_release_hazard_per_hour",
            "adjusted_release_probability",
            "simulated_release_transition",
        ),
    )


def release_response_specification(
    theta_release: float,
    *,
    delay_minutes: int = 0,
    model_id: str = "assumed-release-response",
    model_version: str = RELEASE_RESPONSE_VERSION,
):
    """Create a validated scenario specification for the release channel."""
    specification = AssumptionDrivenResponseSpecification(
        model_id=model_id,
        model_version=model_version,
        contract=release_response_contract(),
        parameters={RELEASE_PARAMETER_NAME: theta_release},
        supported_simulated_outcomes=(
            "adjusted_release_hazard_per_hour",
            "adjusted_release_probability",
        ),
        delay_minutes=delay_minutes,
    )
    specification.validate()
    return specification


def apply_release_response(
    baseline: TransitionHazardEstimate,
    driver_points: Iterable[ResponseDriverPoint],
    specification: AssumptionDrivenResponseSpecification,
    *,
    entity_id: str,
    evaluation_time_utc: datetime,
):
    """Apply the deterministic release hazard shift; do not draw a transition."""
    if evaluation_time_utc.tzinfo is None:
        raise ValueError("Release response evaluation time must include a timezone")
    canonical_contract = release_response_contract()
    specification.validate()
    if specification.contract != canonical_contract:
        raise ValueError("Release response requires the canonical release contract")
    if (baseline.channel != "release_proxy"
            or baseline.source_status != "charging"
            or baseline.destination_status != "available"):
        raise ValueError("Release response requires a charging-to-available baseline")
    if not baseline.locally_qualified or baseline.hazard_per_hour is None:
        raise ValueError("Release response requires a qualified baseline hazard")
    if baseline.hazard_per_hour < 0:
        raise ValueError("Baseline release hazard cannot be negative")

    cutoff = evaluation_time_utc - timedelta(minutes=specification.delay_minutes)
    candidates = []
    seen_times = set()
    for point in driver_points:
        if point.entity_id != entity_id:
            continue
        if point.effective_at_utc.tzinfo is None:
            raise ValueError("Response driver timestamp must include a timezone")
        if point.effective_at_utc > cutoff:
            continue
        point.validate(canonical_contract)
        if point.effective_at_utc in seen_times:
            raise ValueError("Duplicate response driver time for one entity")
        seen_times.add(point.effective_at_utc)
        candidates.append(point)
    if not candidates:
        raise ValueError("No response driver is available at the delayed evaluation time")
    driver = max(candidates, key=lambda item: item.effective_at_utc)

    theta = specification.parameters[RELEASE_PARAMETER_NAME]
    exponent = theta * driver.value
    if exponent > 700 or exponent < -700:
        raise ValueError("Release response exponent is outside numerical safety bounds")
    multiplier = math.exp(exponent)
    adjusted_hazard = baseline.hazard_per_hour * multiplier
    interval_hours = baseline.decision_interval_minutes / 60
    baseline_probability = 1 - math.exp(-baseline.hazard_per_hour * interval_hours)
    adjusted_probability = 1 - math.exp(-adjusted_hazard * interval_hours)
    result = ReleaseResponseResult(
        entity_id=entity_id,
        evaluation_time_utc=evaluation_time_utc,
        driver_time_utc=driver.effective_at_utc,
        driver_value=driver.value,
        driver_unit=driver.driver_unit,
        response_delay_minutes=specification.delay_minutes,
        theta_release=theta,
        theta_release_unit="min/EUR",
        baseline_hazard_per_hour=baseline.hazard_per_hour,
        hazard_multiplier=multiplier,
        adjusted_hazard_per_hour=adjusted_hazard,
        decision_interval_minutes=baseline.decision_interval_minutes,
        baseline_release_probability=baseline_probability,
        adjusted_release_probability=adjusted_probability,
        response_contract_id=canonical_contract.contract_id,
        response_contract_version=canonical_contract.contract_version,
        response_model_id=specification.model_id,
        response_model_version=specification.model_version,
    )
    result.validate()
    return result
