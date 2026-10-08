"""OSA-v1: observable, bounded adaptive scarcity adjustment."""

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
import math

try:
    from .simulation_contract import (
        ObservedSystemState, PolicyKind, PolicySpecification, ProvenanceClass,
    )
except ImportError:  # pragma: no cover
    from simulation_contract import (
        ObservedSystemState, PolicyKind, PolicySpecification, ProvenanceClass,
    )


OSA_POLICY_ID = "observable-scarcity-adjustment"
OSA_POLICY_VERSION = "1.0.0"


class OsaDecisionStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    WITHHELD = "withheld"


@dataclass(frozen=True)
class OsaPolicyParameters:
    scarcity_trigger: float = 0.5
    grace_period_minutes: float = 15.0
    ramp_minutes: float = 30.0
    curvature_gamma: float = 1.2
    maximum_adjustment_eur_per_min: float = 0.05
    minimum_observation_coverage: float = 0.8
    maximum_equipment_unavailability_ratio: float = 0.5

    def validate(self):
        if not 0 <= self.scarcity_trigger < 1:
            raise ValueError("scarcity_trigger must be in [0, 1)")
        if self.grace_period_minutes < 0:
            raise ValueError("grace_period_minutes cannot be negative")
        if self.ramp_minutes <= 0 or self.curvature_gamma <= 0:
            raise ValueError("ramp and curvature must be positive")
        if self.maximum_adjustment_eur_per_min < 0:
            raise ValueError("maximum adjustment cannot be negative")
        if not 0 < self.minimum_observation_coverage <= 1:
            raise ValueError("minimum observation coverage must be in (0, 1]")
        if not 0 <= self.maximum_equipment_unavailability_ratio <= 1:
            raise ValueError("maximum equipment unavailability must be in [0, 1]")
        values = asdict(self).values()
        if any(not math.isfinite(value) for value in values):
            raise ValueError("OSA parameters must be finite")


@dataclass(frozen=True)
class OsaDecision:
    ocpi_location_key: str
    evaluation_time_utc: datetime
    status: OsaDecisionStatus
    reason_code: str
    operational_scarcity_ratio: float | None
    normalized_pressure: float | None
    sustained_condition_minutes: float
    persistence_factor: float | None
    scarcity_signal: float | None
    adaptive_adjustment_eur_per_min: float | None
    policy_id: str = OSA_POLICY_ID
    policy_version: str = OSA_POLICY_VERSION
    provenance: ProvenanceClass = ProvenanceClass.POLICY_DEFINED

    def validate(self, maximum_adjustment):
        if self.evaluation_time_utc.tzinfo is None:
            raise ValueError("OSA decision timestamp must include a timezone")
        if self.sustained_condition_minutes < 0:
            raise ValueError("Sustained scarcity duration cannot be negative")
        for value in (
            self.operational_scarcity_ratio, self.normalized_pressure,
            self.persistence_factor, self.scarcity_signal,
        ):
            if value is not None and not 0 <= value <= 1:
                raise ValueError("OSA signal components must be in [0, 1]")
        adjustment = self.adaptive_adjustment_eur_per_min
        if self.status is OsaDecisionStatus.WITHHELD:
            if adjustment is not None:
                raise ValueError("Withheld OSA decision cannot contain adjustment")
        elif adjustment is None or not 0 <= adjustment <= maximum_adjustment:
            raise ValueError("OSA adjustment is absent or outside its cap")
        if self.status is OsaDecisionStatus.ACTIVE and adjustment <= 0:
            raise ValueError("Active OSA decision requires positive adjustment")
        if self.provenance is not ProvenanceClass.POLICY_DEFINED:
            raise ValueError("OSA decisions must have policy-defined provenance")

    def as_record(self):
        result = asdict(self)
        result["evaluation_time_utc"] = self.evaluation_time_utc.isoformat()
        result["status"] = self.status.value
        result["provenance"] = self.provenance.value
        return result


def osa_policy_specification(parameters: OsaPolicyParameters | None = None):
    parameters = parameters or OsaPolicyParameters()
    parameters.validate()
    specification = PolicySpecification(
        policy_id=OSA_POLICY_ID,
        policy_version=OSA_POLICY_VERSION,
        kind=PolicyKind.ADAPTIVE,
        parameters=asdict(parameters),
        required_derived_statistics=(),
        decision_interval_minutes=5,
        currency="EUR",
    )
    specification.validate()
    return specification


def evaluate_osa_policy(
    state: ObservedSystemState,
    *,
    sustained_condition_minutes: float,
    f1_tariff_available: bool,
    parameters: OsaPolicyParameters | None = None,
):
    """Calculate raw OSA adjustment without F1, lambda or rollout composition."""
    parameters = parameters or OsaPolicyParameters()
    parameters.validate()
    state.validate()
    if sustained_condition_minutes < 0 or not math.isfinite(sustained_condition_minutes):
        raise ValueError("sustained_condition_minutes must be finite and non-negative")

    pressure = (
        1 - state.availability_ratio
        if state.availability_ratio is not None else None
    )
    common = dict(
        ocpi_location_key=state.ocpi_location_key,
        evaluation_time_utc=state.observation_time_utc,
        operational_scarcity_ratio=pressure,
        sustained_condition_minutes=sustained_condition_minutes,
    )
    if not f1_tariff_available:
        return _decision(parameters, common, OsaDecisionStatus.WITHHELD,
                         "f1_tariff_unavailable")
    if (state.valid_observation_coverage is None
            or state.valid_observation_coverage < parameters.minimum_observation_coverage
            or state.zero_availability_evidence is None):
        return _decision(parameters, common, OsaDecisionStatus.WITHHELD,
                         "ineligible_capacity_evidence")
    if state.offered_evse_count <= 0 or state.effective_operational_capacity <= 0:
        return _decision(parameters, common, OsaDecisionStatus.WITHHELD,
                         "no_effective_operational_capacity")
    equipment_ratio = state.non_operational_evse_count / state.offered_evse_count
    if equipment_ratio > parameters.maximum_equipment_unavailability_ratio:
        return _decision(parameters, common, OsaDecisionStatus.WITHHELD,
                         "equipment_unavailability_above_guard")
    if pressure is None:
        return _decision(parameters, common, OsaDecisionStatus.WITHHELD,
                         "availability_ratio_unavailable")
    if state.charging_evse_count <= 0:
        return _decision(parameters, common, OsaDecisionStatus.INACTIVE,
                         "no_charging_evse_for_release_channel")
    if pressure <= parameters.scarcity_trigger:
        return _decision(parameters, common, OsaDecisionStatus.INACTIVE,
                         "scarcity_below_trigger")

    normalized = min(1.0, max(0.0, (
        pressure - parameters.scarcity_trigger
    ) / (1 - parameters.scarcity_trigger)))
    persistence = min(1.0, max(0.0, (
        sustained_condition_minutes - parameters.grace_period_minutes
    ) / parameters.ramp_minutes))
    signal = normalized ** parameters.curvature_gamma * persistence
    adjustment = parameters.maximum_adjustment_eur_per_min * signal
    status = OsaDecisionStatus.ACTIVE if adjustment > 0 else OsaDecisionStatus.INACTIVE
    reason = "adaptive_adjustment_active" if adjustment > 0 else "grace_or_ramp_not_elapsed"
    decision = OsaDecision(
        **common, status=status, reason_code=reason,
        normalized_pressure=normalized, persistence_factor=persistence,
        scarcity_signal=signal,
        adaptive_adjustment_eur_per_min=adjustment,
    )
    decision.validate(parameters.maximum_adjustment_eur_per_min)
    return decision


def evaluate_osa_timeline(
    states,
    *,
    f1_tariff_available: bool,
    parameters: OsaPolicyParameters | None = None,
    expected_cadence_seconds: int = 5 * 60,
    gap_multiplier: float = 2.0,
):
    """Reconstruct sustained-condition duration and evaluate an ordered path."""
    parameters = parameters or OsaPolicyParameters()
    parameters.validate()
    if expected_cadence_seconds <= 0 or gap_multiplier <= 1:
        raise ValueError("Cadence must be positive and gap_multiplier greater than one")
    rows = list(states)
    if not rows:
        return []
    locations = {row.ocpi_location_key for row in rows}
    times = [row.observation_time_utc for row in rows]
    if len(locations) != 1:
        raise ValueError("OSA timeline must contain exactly one location")
    if times != sorted(times) or len(times) != len(set(times)):
        raise ValueError("OSA timeline timestamps must be unique and ordered")

    condition_start = None
    previous_time = None
    result = []
    gap_threshold = expected_cadence_seconds * gap_multiplier
    for state in rows:
        state.validate()
        gap = (
            previous_time is not None
            and (state.observation_time_utc - previous_time).total_seconds()
            > gap_threshold
        )
        qualifies = _qualifies_for_sustained_condition(state, parameters)
        if gap or not qualifies:
            condition_start = None
        if qualifies and condition_start is None:
            condition_start = state.observation_time_utc
        duration = (
            (state.observation_time_utc - condition_start).total_seconds() / 60
            if condition_start is not None else 0.0
        )
        result.append(evaluate_osa_policy(
            state,
            sustained_condition_minutes=duration,
            f1_tariff_available=f1_tariff_available,
            parameters=parameters,
        ))
        previous_time = state.observation_time_utc
    return result


def _qualifies_for_sustained_condition(state, parameters):
    if (state.valid_observation_coverage is None
            or state.valid_observation_coverage < parameters.minimum_observation_coverage
            or state.zero_availability_evidence is None
            or state.offered_evse_count <= 0
            or state.effective_operational_capacity <= 0
            or state.availability_ratio is None
            or state.charging_evse_count <= 0):
        return False
    equipment_ratio = state.non_operational_evse_count / state.offered_evse_count
    pressure = 1 - state.availability_ratio
    return (
        equipment_ratio <= parameters.maximum_equipment_unavailability_ratio
        and pressure > parameters.scarcity_trigger
    )


def _decision(parameters, common, status, reason):
    adjustment = None if status is OsaDecisionStatus.WITHHELD else 0.0
    decision = OsaDecision(
        **common, status=status, reason_code=reason,
        normalized_pressure=None, persistence_factor=None, scarcity_signal=None,
        adaptive_adjustment_eur_per_min=adjustment,
    )
    decision.validate(parameters.maximum_adjustment_eur_per_min)
    return decision
