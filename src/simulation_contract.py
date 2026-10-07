"""Validated contracts for common fixed/adaptive policy evaluation."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping
from zoneinfo import ZoneInfo


CONTRACT_VERSION = "0.1.0"


class ProvenanceClass(str, Enum):
    OBSERVED = "observed"
    RECONSTRUCTED = "reconstructed"
    ESTIMATED = "estimated"
    POLICY_DEFINED = "policy_defined"
    SIMULATED = "simulated"


class ExecutionMode(str, Enum):
    OBSERVED_REPLAY = "observed_replay"
    VALIDATED_COUNTERFACTUAL = "validated_counterfactual"


class PolicyKind(str, Enum):
    FIXED = "fixed"
    ADAPTIVE = "adaptive"


class ClaimScope(str, Enum):
    MECHANISM_ONLY = "mechanism_only"
    COUNTERFACTUAL_EFFECT = "counterfactual_effect"


class EventType(str, Enum):
    OBSERVED_SNAPSHOT = "observed_snapshot"
    OBSERVED_STATUS_TRANSITION = "observed_status_transition"
    POLICY_EVALUATION = "policy_evaluation"
    POLICY_ACTION = "policy_action"
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
    behavioural_response: BehaviouralResponseSpecification | None = None
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

        if self.execution_mode is ExecutionMode.OBSERVED_REPLAY:
            if self.behavioural_response is not None:
                raise ValueError("Observed replay must not include behavioural response")
        else:
            if self.behavioural_response is None:
                raise ValueError("Counterfactual mode requires behavioural response")
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
            EventType.COUNTERFACTUAL_BEHAVIOUR_CHANGE,
            EventType.COUNTERFACTUAL_CAPACITY_RELEASE,
        }
        if execution_mode is ExecutionMode.OBSERVED_REPLAY:
            if self.event_type in counterfactual_types or self.provenance is ProvenanceClass.SIMULATED:
                raise ValueError("Observed replay cannot emit counterfactual events")


@dataclass(frozen=True)
class SimulationResult:
    request_id: str
    policy_id: str
    policy_version: str
    execution_mode: ExecutionMode
    claim_scope: ClaimScope
    events: tuple[SimulationEvent, ...]
    evaluation_metrics: Mapping[str, float | int | str | bool | None]
    contract_version: str = CONTRACT_VERSION

    def validate(self):
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("Unsupported simulator result contract version")
        expected_scope = (
            ClaimScope.MECHANISM_ONLY
            if self.execution_mode is ExecutionMode.OBSERVED_REPLAY
            else ClaimScope.COUNTERFACTUAL_EFFECT
        )
        if self.claim_scope is not expected_scope:
            raise ValueError("Claim scope is inconsistent with execution mode")
        for event in self.events:
            event.validate(self.execution_mode)
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
