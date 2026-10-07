"""Validated contracts for common fixed/adaptive policy evaluation."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping
from zoneinfo import ZoneInfo


CONTRACT_VERSION = "0.3.0"


class ProvenanceClass(str, Enum):
    OBSERVED = "observed"
    RECONSTRUCTED = "reconstructed"
    ESTIMATED = "estimated"
    POLICY_DEFINED = "policy_defined"
    ASSUMED = "assumed"
    SIMULATED = "simulated"


class ExecutionMode(str, Enum):
    OBSERVED_REPLAY = "observed_replay"
    ASSUMPTION_DRIVEN_COUNTERFACTUAL = "assumption_driven_counterfactual"
    VALIDATED_COUNTERFACTUAL = "validated_counterfactual"


class PolicyKind(str, Enum):
    FIXED = "fixed"
    ADAPTIVE = "adaptive"


class AdoptionUnit(str, Enum):
    SITE = "site"
    EVSE = "evse"


class ClaimScope(str, Enum):
    MECHANISM_ONLY = "mechanism_only"
    SCENARIO_CONDITIONAL = "scenario_conditional"
    COUNTERFACTUAL_EFFECT = "counterfactual_effect"


class EventType(str, Enum):
    OBSERVED_SNAPSHOT = "observed_snapshot"
    OBSERVED_STATUS_TRANSITION = "observed_status_transition"
    POLICY_EVALUATION = "policy_evaluation"
    POLICY_ACTION = "policy_action"
    RESPONSE_ASSUMPTION_APPLIED = "response_assumption_applied"
    SIMULATED_STATE_TRANSITION = "simulated_state_transition"
    COUNTERFACTUAL_BEHAVIOUR_CHANGE = "counterfactual_behaviour_change"
    COUNTERFACTUAL_CAPACITY_RELEASE = "counterfactual_capacity_release"


@dataclass(frozen=True)
class EvseStructure:
    ocpi_evse_key: str
    connector_count: int
    max_electric_power_kw: float | None = None

    def validate(self):
        if not self.ocpi_evse_key:
            raise ValueError("EVSE identity is required")
        if self.connector_count < 0:
            raise ValueError("connector_count cannot be negative")
        if self.max_electric_power_kw is not None and self.max_electric_power_kw < 0:
            raise ValueError("max_electric_power_kw cannot be negative")


@dataclass(frozen=True)
class SiteStructure:
    ocpi_location_key: str
    structure_version: str
    local_timezone: str
    evses: tuple[EvseStructure, ...]
    latitude: float | None = None
    longitude: float | None = None
    source_system: str = "OCPI"

    def validate(self):
        if not self.ocpi_location_key or not self.structure_version:
            raise ValueError("Site identity and structure_version are required")
        ZoneInfo(self.local_timezone)
        if not self.evses:
            raise ValueError("A site structure requires at least one EVSE")
        identifiers = [item.ocpi_evse_key for item in self.evses]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("EVSE identities must be unique within a site")
        for evse in self.evses:
            evse.validate()


@dataclass(frozen=True)
class ObservedSystemState:
    ocpi_location_key: str
    observation_time_utc: datetime
    offered_evse_count: int
    available_evse_count: int
    charging_evse_count: int
    reserved_evse_count: int
    non_operational_evse_count: int
    indeterminate_evse_count: int
    effective_operational_capacity: int
    availability_ratio: float | None
    occupancy_proxy: float | None
    zero_availability_evidence: bool | None
    valid_observation_coverage: float | None
    provenance: ProvenanceClass = ProvenanceClass.RECONSTRUCTED

    def validate(self):
        if self.observation_time_utc.tzinfo is None:
            raise ValueError("observation_time_utc must include a timezone")
        counts = (
            self.offered_evse_count,
            self.available_evse_count,
            self.charging_evse_count,
            self.reserved_evse_count,
            self.non_operational_evse_count,
            self.indeterminate_evse_count,
            self.effective_operational_capacity,
        )
        if any(value < 0 for value in counts):
            raise ValueError("System-state counts cannot be negative")
        effective = (
            self.available_evse_count
            + self.charging_evse_count
            + self.reserved_evse_count
        )
        if effective != self.effective_operational_capacity:
            raise ValueError("effective operational capacity is inconsistent")
        if (
            effective
            + self.non_operational_evse_count
            + self.indeterminate_evse_count
            != self.offered_evse_count
        ):
            raise ValueError("offered EVSE partition is inconsistent")
        for name, value in (
            ("availability_ratio", self.availability_ratio),
            ("occupancy_proxy", self.occupancy_proxy),
            ("valid_observation_coverage", self.valid_observation_coverage),
        ):
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if self.provenance is not ProvenanceClass.RECONSTRUCTED:
            raise ValueError("ObservedSystemState must be reconstructed from observations")


@dataclass(frozen=True)
class ObservedChargingPeriod:
    """Observed Session/CDR/meter quantities for one homogeneous period."""
    start_utc: datetime
    end_utc: datetime
    energy_kwh: Decimal = Decimal("0")
    charging_seconds: int = 0
    parking_seconds: int = 0
    average_power_kw: Decimal | None = None
    provenance: ProvenanceClass = ProvenanceClass.OBSERVED

    def validate(self):
        if self.start_utc.tzinfo is None or self.end_utc.tzinfo is None:
            raise ValueError("Charging-period timestamps must include timezones")
        if self.start_utc >= self.end_utc:
            raise ValueError("Charging-period end must be after start")
        if self.energy_kwh < 0 or self.charging_seconds < 0 or self.parking_seconds < 0:
            raise ValueError("Charging-period quantities cannot be negative")
        if self.charging_seconds + self.parking_seconds > (self.end_utc-self.start_utc).total_seconds()+1e-6:
            raise ValueError("Charging plus parking time exceeds period duration")
        if self.provenance is not ProvenanceClass.OBSERVED:
            raise ValueError("Tariff replay accepts only observed usage quantities")


@dataclass(frozen=True)
class ObservedChargingSession:
    connector_key: str
    session_start_utc: datetime
    session_end_utc: datetime
    periods: tuple[ObservedChargingPeriod, ...]
    reservation_restriction: str | None = None
    provenance: ProvenanceClass = ProvenanceClass.OBSERVED

    def validate(self):
        if not self.connector_key or not self.periods:
            raise ValueError("Connector and charging periods are required")
        if self.session_start_utc.tzinfo is None or self.session_end_utc.tzinfo is None:
            raise ValueError("Session timestamps must include timezones")
        if self.session_start_utc >= self.session_end_utc:
            raise ValueError("Session end must be after start")
        previous = self.session_start_utc
        for period in self.periods:
            period.validate()
            if period.start_utc < previous or period.end_utc > self.session_end_utc:
                raise ValueError("Charging periods must be ordered and inside the session")
            previous = period.end_utc
        if self.provenance is not ProvenanceClass.OBSERVED:
            raise ValueError("ObservedChargingSession must have observed provenance")


@dataclass(frozen=True)
class DerivedStatisticInput:
    name: str
    value: float
    unit: str
    estimator_version: str
    training_window_start_utc: datetime
    training_window_end_utc: datetime
    statistically_qualified: bool
    confidence_interval: tuple[float, float] | None = None
    provenance: ProvenanceClass = ProvenanceClass.ESTIMATED

    def validate(self):
        if not self.name or not self.unit or not self.estimator_version:
            raise ValueError("Derived statistic metadata is incomplete")
        if self.training_window_start_utc.tzinfo is None or self.training_window_end_utc.tzinfo is None:
            raise ValueError("Training-window timestamps must include timezones")
        if self.training_window_start_utc >= self.training_window_end_utc:
            raise ValueError("Derived statistic training window is invalid")
        if self.confidence_interval is not None:
            lower, upper = self.confidence_interval
            if lower > self.value or self.value > upper:
                raise ValueError("Estimate must lie inside its confidence interval")
        if self.provenance is not ProvenanceClass.ESTIMATED:
            raise ValueError("DerivedStatisticInput must have estimated provenance")


@dataclass(frozen=True)
class PolicySpecification:
    policy_id: str
    policy_version: str
    kind: PolicyKind
    parameters: Mapping[str, float | int | str | bool]
    required_derived_statistics: tuple[str, ...] = ()
    decision_interval_minutes: int = 5
    currency: str = "EUR"
    provenance: ProvenanceClass = ProvenanceClass.POLICY_DEFINED

    def validate(self):
        if not self.policy_id or not self.policy_version:
            raise ValueError("Policy identity and version are required")
        if self.decision_interval_minutes <= 0:
            raise ValueError("Policy decision interval must be positive")
        if len(self.required_derived_statistics) != len(set(self.required_derived_statistics)):
            raise ValueError("Required derivative statistics must be unique")
        if self.provenance is not ProvenanceClass.POLICY_DEFINED:
            raise ValueError("PolicySpecification must be policy-defined")


@dataclass(frozen=True)
class PolicyActivationWindow:
    """One interval where R_i(t)=1 for a treated site or EVSE."""
    entity_id: str
    active_from_utc: datetime
    active_until_utc: datetime | None = None

    def validate(self):
        if not self.entity_id:
            raise ValueError("Activation-window entity is required")
        if self.active_from_utc.tzinfo is None:
            raise ValueError("Activation-window start must include a timezone")
        if self.active_until_utc is not None:
            if self.active_until_utc.tzinfo is None:
                raise ValueError("Activation-window end must include a timezone")
            if self.active_until_utc <= self.active_from_utc:
                raise ValueError("Activation-window end must be after start")

    def is_active(self, instant: datetime):
        if instant.tzinfo is None:
            raise ValueError("Rollout evaluation time must include a timezone")
        return (
            self.active_from_utc <= instant
            and (self.active_until_utc is None or instant < self.active_until_utc)
        )


@dataclass(frozen=True)
class PolicyAdoptionSpecification:
    """Separates price intensity lambda, coverage kappa and rollout R_i(t)."""
    adoption_id: str
    adoption_version: str
    unit: AdoptionUnit
    price_intensity_lambda: float
    eligible_entity_ids: tuple[str, ...]
    treated_entity_ids: tuple[str, ...]
    activation_windows: tuple[PolicyActivationWindow, ...]
    provenance: ProvenanceClass = ProvenanceClass.POLICY_DEFINED

    @property
    def coverage_fraction_kappa(self):
        return len(self.treated_entity_ids) / len(self.eligible_entity_ids)

    def rollout_state(self, entity_id: str, instant: datetime):
        if entity_id not in self.eligible_entity_ids:
            raise ValueError("Rollout entity is outside the eligible population")
        return int(any(
            window.entity_id == entity_id and window.is_active(instant)
            for window in self.activation_windows
        ))

    def active_coverage_fraction(self, instant: datetime):
        active = sum(self.rollout_state(entity_id, instant)
                     for entity_id in self.eligible_entity_ids)
        return active / len(self.eligible_entity_ids)

    def validate(self, allowed_entity_ids: set[str] | None = None):
        if not self.adoption_id or not self.adoption_version:
            raise ValueError("Adoption identity and version are required")
        if not 0 <= self.price_intensity_lambda <= 1:
            raise ValueError("price_intensity_lambda must be between zero and one")
        eligible = set(self.eligible_entity_ids)
        treated = set(self.treated_entity_ids)
        if not eligible or len(eligible) != len(self.eligible_entity_ids):
            raise ValueError("Eligible rollout entities must be non-empty and unique")
        if len(treated) != len(self.treated_entity_ids):
            raise ValueError("Treated rollout entities must be unique")
        if not treated <= eligible:
            raise ValueError("Treated rollout entities must be eligible")
        if allowed_entity_ids is not None and not eligible <= allowed_entity_ids:
            raise ValueError("Rollout entities are absent from the supplied structure")
        if self.provenance is not ProvenanceClass.POLICY_DEFINED:
            raise ValueError("Adoption design must have policy-defined provenance")
        for window in self.activation_windows:
            window.validate()
        window_entities = {window.entity_id for window in self.activation_windows}
        if window_entities != treated:
            raise ValueError("Every treated entity must have rollout windows and no others")
        by_entity: dict[str, list[PolicyActivationWindow]] = {}
        for window in self.activation_windows:
            by_entity.setdefault(window.entity_id, []).append(window)
        for windows in by_entity.values():
            ordered = sorted(windows, key=lambda item: item.active_from_utc)
            for previous, current in zip(ordered, ordered[1:]):
                if previous.active_until_utc is None or previous.active_until_utc > current.active_from_utc:
                    raise ValueError("Rollout windows for one entity cannot overlap")


@dataclass(frozen=True)
class AssumptionDrivenResponseSpecification:
    """A versioned, explicitly hypothetical price-response mechanism."""
    model_id: str
    model_version: str
    functional_form: str
    response_channels: tuple[str, ...]
    affected_transitions: tuple[str, ...]
    parameters: Mapping[str, float | int | str | bool]
    parameter_units: Mapping[str, str]
    supported_simulated_outcomes: tuple[str, ...]
    delay_minutes: int = 0
    provenance: ProvenanceClass = ProvenanceClass.ASSUMED

    def validate(self):
        if not self.model_id or not self.model_version or not self.functional_form:
            raise ValueError("Assumed response identity and functional form are required")
        if not self.response_channels or len(self.response_channels) != len(set(self.response_channels)):
            raise ValueError("Assumed response channels must be non-empty and unique")
        if not self.affected_transitions or len(self.affected_transitions) != len(set(self.affected_transitions)):
            raise ValueError("Affected transitions must be non-empty and unique")
        if not self.parameters:
            raise ValueError("Assumed response parameters are required")
        if set(self.parameters) != set(self.parameter_units):
            raise ValueError("Every assumed parameter must have exactly one declared unit")
        if self.delay_minutes < 0:
            raise ValueError("Response delay cannot be negative")
        if not self.supported_simulated_outcomes:
            raise ValueError("Assumed response must declare supported simulated outcomes")
        if self.provenance is not ProvenanceClass.ASSUMED:
            raise ValueError("Hypothetical response parameters must have assumed provenance")


@dataclass(frozen=True)
class BehaviouralResponseSpecification:
    model_id: str
    model_version: str
    evidence_source: str
    validation_report: str
    validated_for_vilnius: bool
    supported_outcomes: tuple[str, ...]
    provenance: ProvenanceClass = ProvenanceClass.ESTIMATED

    def validate(self):
        if not all((self.model_id, self.model_version, self.evidence_source,
                    self.validation_report)):
            raise ValueError("Behavioural response evidence metadata is incomplete")
        if not self.validated_for_vilnius:
            raise ValueError("Counterfactual response must be validated for Vilnius")
        if not self.supported_outcomes:
            raise ValueError("Behavioural response must declare supported outcomes")
        if self.provenance is not ProvenanceClass.ESTIMATED:
            raise ValueError("Behavioural response must have estimated provenance")


@dataclass(frozen=True)
class SimulationRequest:
    request_id: str
    structure: SiteStructure
    observed_timeline: tuple[ObservedSystemState, ...]
    policy: PolicySpecification
    execution_mode: ExecutionMode = ExecutionMode.OBSERVED_REPLAY
    derived_statistics: tuple[DerivedStatisticInput, ...] = ()
    observed_sessions: tuple[ObservedChargingSession, ...] = ()
    adoption: PolicyAdoptionSpecification | None = None
    assumed_response: AssumptionDrivenResponseSpecification | None = None
    behavioural_response: BehaviouralResponseSpecification | None = None
    random_seed: int | None = None
    contract_version: str = CONTRACT_VERSION

    def validate(self):
        if not self.request_id:
            raise ValueError("request_id is required")
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("Unsupported simulator contract version")
        self.structure.validate()
        self.policy.validate()
        if not self.observed_timeline:
            raise ValueError("Observed timeline cannot be empty")
        times = []
        for state in self.observed_timeline:
            state.validate()
            if state.ocpi_location_key != self.structure.ocpi_location_key:
                raise ValueError("Timeline state belongs to another site")
            times.append(state.observation_time_utc)
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValueError("Timeline timestamps must be unique and ordered")

        statistics = {item.name: item for item in self.derived_statistics}
        if len(statistics) != len(self.derived_statistics):
            raise ValueError("Derived statistic names must be unique")
        for statistic in self.derived_statistics:
            statistic.validate()
        for session in self.observed_sessions:
            session.validate()
        if self.adoption is not None:
            allowed_entities = (
                {self.structure.ocpi_location_key}
                if self.adoption.unit is AdoptionUnit.SITE
                else {evse.ocpi_evse_key for evse in self.structure.evses}
            )
            self.adoption.validate(allowed_entities)
        missing = set(self.policy.required_derived_statistics) - set(statistics)
        if missing:
            raise ValueError(f"Required derivative statistics are missing: {sorted(missing)}")
        unqualified = [
            name for name in self.policy.required_derived_statistics
            if not statistics[name].statistically_qualified
        ]
        if unqualified:
            raise ValueError(
                f"Required derivative statistics are not qualified: {unqualified}"
            )

        if self.random_seed is not None and self.random_seed < 0:
            raise ValueError("random_seed must be non-negative")
        if self.execution_mode is ExecutionMode.OBSERVED_REPLAY:
            if self.assumed_response is not None or self.behavioural_response is not None:
                raise ValueError("Observed replay must not include a response model")
        elif self.execution_mode is ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL:
            if self.assumed_response is None:
                raise ValueError("Assumption-driven mode requires an assumed response")
            if self.adoption is None:
                raise ValueError("Assumption-driven mode requires an adoption specification")
            if self.behavioural_response is not None:
                raise ValueError("Assumption-driven mode cannot label a response as validated")
            if self.random_seed is None:
                raise ValueError("Assumption-driven mode requires a deterministic random_seed")
            self.assumed_response.validate()
        else:
            if self.behavioural_response is None:
                raise ValueError("Validated counterfactual mode requires behavioural response")
            if self.adoption is None:
                raise ValueError("Validated counterfactual mode requires an adoption specification")
            if self.assumed_response is not None:
                raise ValueError("Validated counterfactual mode cannot use assumed response parameters")
            self.behavioural_response.validate()


@dataclass(frozen=True)
class SimulationEvent:
    event_time_utc: datetime
    event_type: EventType
    provenance: ProvenanceClass
    payload: Mapping[str, float | int | str | bool | None] = field(default_factory=dict)

    def validate(self, execution_mode):
        if self.event_time_utc.tzinfo is None:
            raise ValueError("Event timestamp must include a timezone")
        counterfactual_types = {
            EventType.SIMULATED_STATE_TRANSITION,
            EventType.COUNTERFACTUAL_BEHAVIOUR_CHANGE,
            EventType.COUNTERFACTUAL_CAPACITY_RELEASE,
        }
        if execution_mode is ExecutionMode.OBSERVED_REPLAY:
            if self.event_type in counterfactual_types or self.provenance is ProvenanceClass.SIMULATED:
                raise ValueError("Observed replay cannot emit counterfactual events")
            if self.event_type is EventType.RESPONSE_ASSUMPTION_APPLIED:
                raise ValueError("Observed replay cannot apply response assumptions")
        if self.event_type is EventType.RESPONSE_ASSUMPTION_APPLIED:
            if execution_mode is not ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL:
                raise ValueError("Response-assumption events require assumption-driven mode")
            if self.provenance is not ProvenanceClass.ASSUMED:
                raise ValueError("Response-assumption events must have assumed provenance")
        if self.event_type in counterfactual_types and self.provenance is not ProvenanceClass.SIMULATED:
            raise ValueError("Counterfactual state events must have simulated provenance")


@dataclass(frozen=True)
class AdoptionResultMetadata:
    adoption_id: str
    adoption_version: str
    unit: AdoptionUnit
    price_intensity_lambda: float
    target_coverage_fraction_kappa: float
    minimum_active_coverage_fraction: float
    maximum_active_coverage_fraction: float

    def validate(self):
        if not self.adoption_id or not self.adoption_version:
            raise ValueError("Result adoption identity and version are required")
        values = (
            self.price_intensity_lambda,
            self.target_coverage_fraction_kappa,
            self.minimum_active_coverage_fraction,
            self.maximum_active_coverage_fraction,
        )
        if any(not 0 <= value <= 1 for value in values):
            raise ValueError("Result adoption ratios must be between zero and one")
        if self.minimum_active_coverage_fraction > self.maximum_active_coverage_fraction:
            raise ValueError("Minimum active coverage cannot exceed maximum")
        if self.maximum_active_coverage_fraction > self.target_coverage_fraction_kappa:
            raise ValueError("Active coverage cannot exceed target coverage")


@dataclass(frozen=True)
class SimulationResult:
    request_id: str
    policy_id: str
    policy_version: str
    execution_mode: ExecutionMode
    claim_scope: ClaimScope
    events: tuple[SimulationEvent, ...]
    evaluation_metrics: Mapping[str, float | int | str | bool | None]
    adoption_summary: AdoptionResultMetadata | None = None
    assumption_disclosure: str | None = None
    response_model_id: str | None = None
    response_model_version: str | None = None
    contract_version: str = CONTRACT_VERSION

    def validate(self):
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("Unsupported simulator result contract version")
        expected_scope = {
            ExecutionMode.OBSERVED_REPLAY: ClaimScope.MECHANISM_ONLY,
            ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL: ClaimScope.SCENARIO_CONDITIONAL,
            ExecutionMode.VALIDATED_COUNTERFACTUAL: ClaimScope.COUNTERFACTUAL_EFFECT,
        }[self.execution_mode]
        if self.claim_scope is not expected_scope:
            raise ValueError("Claim scope is inconsistent with execution mode")
        for event in self.events:
            event.validate(self.execution_mode)
        if self.adoption_summary is not None:
            self.adoption_summary.validate()
        forbidden_replay_metrics = {
            "capacity_released_by_fee",
            "waiting_time_reduction",
            "queue_length_reduction",
            "users_changing_behaviour",
        }
        if self.execution_mode is ExecutionMode.OBSERVED_REPLAY:
            forbidden = forbidden_replay_metrics & set(self.evaluation_metrics)
            if forbidden:
                raise ValueError(
                    f"Observed replay cannot report causal metrics: {sorted(forbidden)}"
                )
            if any((self.assumption_disclosure, self.response_model_id,
                    self.response_model_version)):
                raise ValueError("Observed replay must not report a response model")
        elif self.execution_mode is ExecutionMode.ASSUMPTION_DRIVEN_COUNTERFACTUAL:
            if self.adoption_summary is None:
                raise ValueError("Assumption-driven results require adoption metadata")
            if not all((self.assumption_disclosure, self.response_model_id,
                        self.response_model_version)):
                raise ValueError(
                    "Assumption-driven results require model identity and disclosure"
                )
            forbidden = forbidden_replay_metrics & set(self.evaluation_metrics)
            if forbidden:
                raise ValueError(
                    "Assumption-driven metrics must be explicitly named as simulated "
                    f"or scenario-conditional: {sorted(forbidden)}"
                )
        else:
            if self.adoption_summary is None:
                raise ValueError("Validated results require adoption metadata")
            if not self.response_model_id or not self.response_model_version:
                raise ValueError("Validated results require response model identity")


def observed_system_state_from_capacity_snapshot(snapshot):
    """Adapt a flow.SiteCapacitySnapshot to the simulator input contract."""
    state = ObservedSystemState(
        ocpi_location_key=snapshot.ocpi_location_key,
        observation_time_utc=snapshot.observation_time_utc,
        offered_evse_count=snapshot.offered_evse_count,
        available_evse_count=snapshot.available_evse_count,
        charging_evse_count=snapshot.charging_evse_count,
        reserved_evse_count=snapshot.reserved_evse_count,
        non_operational_evse_count=snapshot.non_operational_evse_count,
        indeterminate_evse_count=snapshot.indeterminate_evse_count,
        effective_operational_capacity=snapshot.effective_operational_capacity,
        availability_ratio=snapshot.availability_ratio,
        occupancy_proxy=snapshot.occupancy_proxy,
        zero_availability_evidence=snapshot.zero_availability,
        valid_observation_coverage=snapshot.valid_observation_coverage,
    )
    state.validate()
    return state
