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
        ResponseSignalState,
        TypedResponseSignalPoint,
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
        ResponseSignalState,
        TypedResponseSignalPoint,
    )
    from transition_model import TransitionHazardEstimate


RELEASE_RESPONSE_VERSION = "1.0.0"
RELEASE_CONTRACT_ID = "release-hazard-exponential-shift"
RELEASE_DRIVER_NAME = "effective_policy_adjustment"
RELEASE_DRIVER_UNIT = "EUR/min"
RELEASE_PARAMETER_NAME = "theta_release"

RELEASE_V2_VERSION = "2.0.0"
RELEASE_V2_CONTRACT_ID = "release-hazard-typed-exponential-shift"
ORIGIN_PRICE_SIGNAL_NAME = "origin_price_contribution_rate"
ORIGIN_PRICE_SIGNAL_UNIT = "EUR/min"
RELEASE_CREDIT_SIGNAL_NAME = "release_credit_offer"
RELEASE_CREDIT_SIGNAL_UNIT = "MCU"


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


@dataclass(frozen=True)
class ReleaseResponseV2Specification:
    model_id: str
    model_version: str
    theta_release_price: float
    theta_release_credit: float = 0.0
    delay_release_price_minutes: int = 0
    delay_release_credit_minutes: int = 0
    release_credit_applicable: bool = False
    provenance: ProvenanceClass = ProvenanceClass.ASSUMED

    def validate(self):
        if not self.model_id or not self.model_version:
            raise ValueError("Release v2 response identity is required")
        values = (self.theta_release_price, self.theta_release_credit)
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("Release v2 sensitivities must be finite and non-negative")
        delays = (
            self.delay_release_price_minutes,
            self.delay_release_credit_minutes,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in delays):
            raise ValueError("Release v2 delays must be non-negative integer minutes")
        if not self.release_credit_applicable and self.theta_release_credit != 0:
            raise ValueError(
                "Non-applicable release credit requires zero credit sensitivity"
            )
        if self.provenance is not ProvenanceClass.ASSUMED:
            raise ValueError("Release v2 response parameters must be assumed")


@dataclass(frozen=True)
class ReleaseResponseV2Result:
    entity_id: str
    evaluation_time_utc: datetime
    price_signal_time_utc: datetime
    price_signal_value_eur_per_min: float
    release_credit_applicable: bool
    credit_signal_time_utc: datetime | None
    credit_signal_value_mcu: int | None
    theta_release_price: float
    theta_release_credit: float
    delay_release_price_minutes: int
    delay_release_credit_minutes: int
    price_exponent_component: float
    credit_exponent_component: float
    total_exponent: float
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
        if self.evaluation_time_utc.tzinfo is None or self.price_signal_time_utc.tzinfo is None:
            raise ValueError("Release v2 timestamps must include timezones")
        if self.price_signal_time_utc > self.evaluation_time_utc - timedelta(
            minutes=self.delay_release_price_minutes
        ):
            raise ValueError("Release v2 price signal violates its delay")
        if self.release_credit_applicable:
            if self.credit_signal_time_utc is None or self.credit_signal_value_mcu is None:
                raise ValueError("Applicable release credit requires a selected signal")
            if self.credit_signal_time_utc.tzinfo is None:
                raise ValueError("Release v2 credit timestamp must include a timezone")
            if self.credit_signal_time_utc > self.evaluation_time_utc - timedelta(
                minutes=self.delay_release_credit_minutes
            ):
                raise ValueError("Release v2 credit signal violates its delay")
        elif self.credit_signal_time_utc is not None or self.credit_signal_value_mcu is not None:
            raise ValueError("Non-applicable release credit cannot expose a numeric signal")
        numeric = (
            self.price_signal_value_eur_per_min, self.theta_release_price,
            self.theta_release_credit, self.price_exponent_component,
            self.credit_exponent_component, self.total_exponent,
            self.baseline_hazard_per_hour, self.hazard_multiplier,
            self.adjusted_hazard_per_hour, self.baseline_release_probability,
            self.adjusted_release_probability,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("Release v2 response values must be finite")
        if min(self.price_signal_value_eur_per_min, self.theta_release_price,
               self.theta_release_credit, self.price_exponent_component,
               self.credit_exponent_component, self.total_exponent,
               self.baseline_hazard_per_hour, self.hazard_multiplier,
               self.adjusted_hazard_per_hour) < 0:
            raise ValueError("Release v2 drivers, sensitivities and hazards cannot be negative")
        if self.total_exponent > 700:
            raise ValueError("Release v2 exponent is outside numerical safety bounds")
        if self.credit_signal_value_mcu is not None:
            if (isinstance(self.credit_signal_value_mcu, bool)
                    or not isinstance(self.credit_signal_value_mcu, int)
                    or self.credit_signal_value_mcu < 0):
                raise ValueError("Release-credit signal must be a non-negative integer MCU")
        if not math.isclose(
            self.total_exponent,
            self.price_exponent_component + self.credit_exponent_component,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("Release v2 exponent components do not reconcile")
        if not math.isclose(
            self.hazard_multiplier, math.exp(self.total_exponent),
            rel_tol=1e-12, abs_tol=1e-12,
        ):
            raise ValueError("Release v2 hazard multiplier is inconsistent")
        if not math.isclose(
            self.adjusted_hazard_per_hour,
            self.baseline_hazard_per_hour * self.hazard_multiplier,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("Release v2 adjusted hazard is inconsistent")
        if not 0 <= self.baseline_release_probability <= 1:
            raise ValueError("Baseline release probability must be in [0, 1]")
        if not 0 <= self.adjusted_release_probability <= 1:
            raise ValueError("Adjusted release probability must be in [0, 1]")
        if self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Adjusted release v2 response must be simulated")

    def as_record(self):
        result = asdict(self)
        for key in ("evaluation_time_utc", "price_signal_time_utc", "credit_signal_time_utc"):
            value = result[key]
            result[key] = value.isoformat() if value is not None else None
        result["provenance"] = self.provenance.value
        return result


def release_response_v2_specification(
    theta_release_price: float,
    *,
    theta_release_credit: float = 0.0,
    delay_release_price_minutes: int = 0,
    delay_release_credit_minutes: int = 0,
    release_credit_applicable: bool = False,
    model_id: str = "assumed-release-response-v2",
    model_version: str = RELEASE_V2_VERSION,
):
    specification = ReleaseResponseV2Specification(
        model_id=model_id,
        model_version=model_version,
        theta_release_price=theta_release_price,
        theta_release_credit=theta_release_credit,
        delay_release_price_minutes=delay_release_price_minutes,
        delay_release_credit_minutes=delay_release_credit_minutes,
        release_credit_applicable=release_credit_applicable,
    )
    specification.validate()
    return specification


def typed_price_signal_from_v1(point: ResponseDriverPoint):
    """Map the existing EUR/min driver to v2 without changing its lineage."""
    if point.withheld:
        if (not point.entity_id or point.effective_at_utc.tzinfo is None
                or point.value is not None or not point.reason_code
                or point.driver_name != RELEASE_DRIVER_NAME
                or point.driver_unit != RELEASE_DRIVER_UNIT
                or point.provenance is not ProvenanceClass.POLICY_DEFINED):
            raise ValueError("Withheld v1 driver is invalid")
    else:
        point.validate(release_response_contract())
    if point.withheld:
        state = ResponseSignalState.WITHHELD
        value = None
    else:
        state = ResponseSignalState.AVAILABLE
        value = point.value
    return TypedResponseSignalPoint(
        entity_id=point.entity_id,
        effective_at_utc=point.effective_at_utc,
        signal_name=ORIGIN_PRICE_SIGNAL_NAME,
        signal_unit=ORIGIN_PRICE_SIGNAL_UNIT,
        state=state,
        value=value,
        source_event_id=(
            f"v1-driver:{point.entity_id}:{point.effective_at_utc.isoformat()}"
        ),
        reason_code=point.reason_code,
        provenance=point.provenance,
    )


def _latest_typed_signal(
    points: Iterable[TypedResponseSignalPoint],
    *,
    entity_id: str,
    evaluation_time_utc: datetime,
    delay_minutes: int,
    expected_name: str,
    expected_unit: str,
    allowed_provenance: tuple[ProvenanceClass, ...],
):
    cutoff = evaluation_time_utc - timedelta(minutes=delay_minutes)
    candidates = []
    seen_times = set()
    for point in points:
        if point.entity_id != entity_id:
            continue
        point.validate(
            expected_name=expected_name,
            expected_unit=expected_unit,
            allowed_provenance=allowed_provenance,
        )
        if point.effective_at_utc in seen_times:
            raise ValueError("Duplicate typed response signal time for one entity")
        seen_times.add(point.effective_at_utc)
        if point.effective_at_utc <= cutoff:
            candidates.append(point)
    if not candidates:
        raise ValueError(f"No {expected_name} signal is available at the delayed evaluation time")
    return max(candidates, key=lambda item: item.effective_at_utc)


def apply_release_response_v2(
    baseline: TransitionHazardEstimate,
    price_signal_points: Iterable[TypedResponseSignalPoint],
    specification: ReleaseResponseV2Specification,
    *,
    entity_id: str,
    evaluation_time_utc: datetime,
    credit_signal_points: Iterable[TypedResponseSignalPoint] = (),
):
    """Apply typed price and optional release-credit terms; never draw state."""
    if evaluation_time_utc.tzinfo is None:
        raise ValueError("Release v2 evaluation time must include a timezone")
    specification.validate()
    if (baseline.channel != "release_proxy"
            or baseline.source_status != "charging"
            or baseline.destination_status != "available"):
        raise ValueError("Release v2 requires a charging-to-available baseline")
    if not baseline.locally_qualified or baseline.hazard_per_hour is None:
        raise ValueError("Release v2 requires a qualified baseline hazard")
    if baseline.hazard_per_hour < 0:
        raise ValueError("Baseline release hazard cannot be negative")

    price = _latest_typed_signal(
        price_signal_points,
        entity_id=entity_id,
        evaluation_time_utc=evaluation_time_utc,
        delay_minutes=specification.delay_release_price_minutes,
        expected_name=ORIGIN_PRICE_SIGNAL_NAME,
        expected_unit=ORIGIN_PRICE_SIGNAL_UNIT,
        allowed_provenance=(ProvenanceClass.POLICY_DEFINED,),
    )
    if price.state is not ResponseSignalState.AVAILABLE:
        raise ValueError(f"Release v2 price signal is {price.state.value}: {price.reason_code}")
    if price.value < 0:
        raise ValueError("Origin price contribution rate cannot be negative")

    credit = None
    credit_points = tuple(credit_signal_points)
    if specification.release_credit_applicable:
        credit = _latest_typed_signal(
            credit_points,
            entity_id=entity_id,
            evaluation_time_utc=evaluation_time_utc,
            delay_minutes=specification.delay_release_credit_minutes,
            expected_name=RELEASE_CREDIT_SIGNAL_NAME,
            expected_unit=RELEASE_CREDIT_SIGNAL_UNIT,
            allowed_provenance=(ProvenanceClass.SIMULATED,),
        )
        if credit.state is not ResponseSignalState.AVAILABLE:
            raise ValueError(
                f"Release v2 credit signal is {credit.state.value}: {credit.reason_code}"
            )
        if (isinstance(credit.value, bool) or not isinstance(credit.value, int)
                or credit.value < 0):
            raise ValueError("Release-credit signal must be a non-negative integer MCU")
    elif credit_points:
        for point in credit_points:
            if point.entity_id != entity_id:
                continue
            point.validate(
                expected_name=RELEASE_CREDIT_SIGNAL_NAME,
                expected_unit=RELEASE_CREDIT_SIGNAL_UNIT,
                allowed_provenance=(ProvenanceClass.SIMULATED,),
            )
            if point.state is not ResponseSignalState.NOT_APPLICABLE:
                raise ValueError(
                    "Non-applicable release-credit profile cannot ignore an active signal"
                )

    price_component = specification.theta_release_price * price.value
    credit_component = (
        specification.theta_release_credit * credit.value if credit is not None else 0.0
    )
    exponent = price_component + credit_component
    if exponent > 700 or exponent < -700:
        raise ValueError("Release v2 exponent is outside numerical safety bounds")
    multiplier = math.exp(exponent)
    adjusted_hazard = baseline.hazard_per_hour * multiplier
    interval_hours = baseline.decision_interval_minutes / 60
    baseline_probability = 1 - math.exp(-baseline.hazard_per_hour * interval_hours)
    adjusted_probability = 1 - math.exp(-adjusted_hazard * interval_hours)
    result = ReleaseResponseV2Result(
        entity_id=entity_id,
        evaluation_time_utc=evaluation_time_utc,
        price_signal_time_utc=price.effective_at_utc,
        price_signal_value_eur_per_min=float(price.value),
        release_credit_applicable=specification.release_credit_applicable,
        credit_signal_time_utc=credit.effective_at_utc if credit else None,
        credit_signal_value_mcu=credit.value if credit else None,
        theta_release_price=specification.theta_release_price,
        theta_release_credit=specification.theta_release_credit,
        delay_release_price_minutes=specification.delay_release_price_minutes,
        delay_release_credit_minutes=specification.delay_release_credit_minutes,
        price_exponent_component=price_component,
        credit_exponent_component=credit_component,
        total_exponent=exponent,
        baseline_hazard_per_hour=baseline.hazard_per_hour,
        hazard_multiplier=multiplier,
        adjusted_hazard_per_hour=adjusted_hazard,
        decision_interval_minutes=baseline.decision_interval_minutes,
        baseline_release_probability=baseline_probability,
        adjusted_release_probability=adjusted_probability,
        response_contract_id=RELEASE_V2_CONTRACT_ID,
        response_contract_version=RELEASE_V2_VERSION,
        response_model_id=specification.model_id,
        response_model_version=specification.model_version,
    )
    result.validate()
    return result


def release_response_contract():
    """Return the original scalar v1 compatibility contract."""
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
