"""Compose factual F1, OSA-v1, adoption and the release-response driver."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

try:
    from .adaptive_policy import OsaDecision, OsaDecisionStatus
    from .fixed_policy import (
        POLICY_ID as F1_POLICY_ID, POLICY_VERSION as F1_POLICY_VERSION,
        ObservedTariff, ReplayStatus, TariffReplayResult,
    )
    from .release_response import RELEASE_DRIVER_NAME, RELEASE_DRIVER_UNIT
    from .simulation_contract import (
        AdoptionUnit, PolicyAdoptionSpecification, ProvenanceClass,
        ResponseDriverPoint,
    )
except ImportError:  # pragma: no cover
    from adaptive_policy import OsaDecision, OsaDecisionStatus
    from fixed_policy import (
        POLICY_ID as F1_POLICY_ID, POLICY_VERSION as F1_POLICY_VERSION,
        ObservedTariff, ReplayStatus, TariffReplayResult,
    )
    from release_response import RELEASE_DRIVER_NAME, RELEASE_DRIVER_UNIT
    from simulation_contract import (
        AdoptionUnit, PolicyAdoptionSpecification, ProvenanceClass,
        ResponseDriverPoint,
    )


INTEGRATION_VERSION = "1.0.0"


class CompositionStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    WITHHELD = "withheld"


@dataclass(frozen=True)
class AdaptiveTariffComposition:
    evaluation_time_utc: datetime
    entity_id: str
    connector_key: str
    status: CompositionStatus
    reason_code: str
    f1_policy_id: str
    f1_policy_version: str
    f1_tariff_key: str | None
    f1_tariff_revision_id: int | None
    f1_component_types: tuple[str, ...]
    currency: str | None
    f1_published_total: Decimal | None
    osa_policy_id: str
    osa_policy_version: str
    raw_adjustment_eur_per_min: Decimal | None
    price_intensity_lambda: Decimal
    rollout_state: int
    target_coverage_fraction_kappa: Decimal
    effective_policy_adjustment_eur_per_min: Decimal | None
    counterfactual_time_component_eur_per_hour: Decimal | None
    counterfactual_total: Decimal | None
    counterfactual_total_reason: str
    response_driver: ResponseDriverPoint | None
    provenance: ProvenanceClass = ProvenanceClass.POLICY_DEFINED
    integration_version: str = INTEGRATION_VERSION

    def validate(self):
        if self.evaluation_time_utc.tzinfo is None:
            raise ValueError("Composition timestamp must include a timezone")
        if self.rollout_state not in (0, 1):
            raise ValueError("Rollout state must be zero or one")
        if not Decimal("0") <= self.price_intensity_lambda <= Decimal("1"):
            raise ValueError("Price intensity must be in [0, 1]")
        if not Decimal("0") <= self.target_coverage_fraction_kappa <= Decimal("1"):
            raise ValueError("Coverage must be in [0, 1]")
        if self.counterfactual_total is not None:
            raise ValueError("Counterfactual total requires observed adjustment duration")
        if self.status is CompositionStatus.WITHHELD:
            values = (
                self.raw_adjustment_eur_per_min,
                self.effective_policy_adjustment_eur_per_min,
                self.counterfactual_time_component_eur_per_hour,
                self.response_driver,
            )
            if any(value is not None for value in values):
                raise ValueError("Withheld composition cannot expose an adjustment driver")
        else:
            if any(value is None for value in (
                self.raw_adjustment_eur_per_min,
                self.effective_policy_adjustment_eur_per_min,
                self.counterfactual_time_component_eur_per_hour,
                self.response_driver,
            )):
                raise ValueError("Valid composition requires adjustment and driver fields")
            expected = (
                self.raw_adjustment_eur_per_min
                * self.price_intensity_lambda
                * self.rollout_state
            )
            if self.effective_policy_adjustment_eur_per_min != expected:
                raise ValueError("Effective adjustment is inconsistent with lambda and rollout")
            if self.counterfactual_time_component_eur_per_hour != expected * 60:
                raise ValueError("Counterfactual TIME component has inconsistent units")
            if Decimal(str(self.response_driver.value)) != expected:
                raise ValueError("Response driver differs from effective adjustment")
            if (self.response_driver.entity_id != self.entity_id
                    or self.response_driver.effective_at_utc != self.evaluation_time_utc
                    or self.response_driver.driver_name != RELEASE_DRIVER_NAME
                    or self.response_driver.driver_unit != RELEASE_DRIVER_UNIT):
                raise ValueError("Response driver identity is inconsistent")
            if self.status is CompositionStatus.ACTIVE and expected <= 0:
                raise ValueError("Active composition requires positive adjustment")
            if self.status is CompositionStatus.INACTIVE and expected != 0:
                raise ValueError("Inactive composition requires zero adjustment")
        if self.provenance is not ProvenanceClass.POLICY_DEFINED:
            raise ValueError("Tariff composition must be policy-defined")

    def as_record(self):
        def convert(value):
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, dict):
                return {key: convert(item) for key, item in value.items()}
            return value
        return convert(asdict(self))


def compose_adaptive_tariff(
    f1_tariff: ObservedTariff | None,
    osa_decision: OsaDecision,
    adoption: PolicyAdoptionSpecification,
    *,
    connector_key: str,
    entity_id: str,
    evaluation_time_utc: datetime,
    f1_replay_result: TariffReplayResult | None = None,
):
    """Compose a component-aware tariff decision and release-response driver."""
    if evaluation_time_utc.tzinfo is None:
        raise ValueError("Composition time must include a timezone")
    if osa_decision.evaluation_time_utc != evaluation_time_utc:
        raise ValueError("OSA and composition evaluation timestamps must match")
    if not connector_key:
        raise ValueError("Connector identity is required for tariff composition")
    adoption.validate()
    if (adoption.unit is AdoptionUnit.SITE
            and entity_id != osa_decision.ocpi_location_key):
        raise ValueError("Site-level rollout entity must match the OSA location")
    rollout = adoption.rollout_state(entity_id, evaluation_time_utc)
    intensity = Decimal(str(adoption.price_intensity_lambda))
    coverage = Decimal(str(adoption.coverage_fraction_kappa))
    base = dict(
        evaluation_time_utc=evaluation_time_utc,
        entity_id=entity_id,
        connector_key=connector_key,
        f1_policy_id=F1_POLICY_ID,
        f1_policy_version=F1_POLICY_VERSION,
        f1_tariff_key=f1_tariff.tariff_key if f1_tariff else None,
        f1_tariff_revision_id=f1_tariff.revision_id if f1_tariff else None,
        f1_component_types=tuple(sorted({
            component.component_type
            for element in f1_tariff.elements
            for component in element.components
        })) if f1_tariff else (),
        currency=f1_tariff.currency if f1_tariff else None,
        f1_published_total=None,
        osa_policy_id=osa_decision.policy_id,
        osa_policy_version=osa_decision.policy_version,
        price_intensity_lambda=intensity,
        rollout_state=rollout,
        target_coverage_fraction_kappa=coverage,
        counterfactual_total=None,
        counterfactual_total_reason="requires_observed_adjustment_duration",
    )
    if f1_tariff is None:
        return _withheld(base, "f1_tariff_unavailable")
    if f1_tariff.currency != "EUR":
        return _withheld(base, "f1_currency_not_eur")
    if (f1_tariff.valid_from is not None
            and evaluation_time_utc < f1_tariff.valid_from):
        return _withheld(base, "f1_tariff_not_yet_valid")
    if (f1_tariff.valid_to is not None
            and evaluation_time_utc >= f1_tariff.valid_to):
        return _withheld(base, "f1_tariff_expired")
    if not base["f1_component_types"]:
        return _withheld(base, "f1_tariff_has_no_price_components")
    if osa_decision.status is OsaDecisionStatus.WITHHELD:
        return _withheld(base, f"osa_withheld:{osa_decision.reason_code}")
    if osa_decision.provenance is not ProvenanceClass.POLICY_DEFINED:
        raise ValueError("OSA decision must have policy-defined provenance")
    if f1_replay_result is not None:
        if (f1_replay_result.connector_key != connector_key
                or (f1_replay_result.tariff_key is not None
                    and f1_replay_result.tariff_key != f1_tariff.tariff_key)
                or (f1_replay_result.tariff_revision_id is not None
                    and f1_replay_result.tariff_revision_id != f1_tariff.revision_id)):
            raise ValueError("F1 replay result does not match the tariff composition")
        if f1_replay_result.status is ReplayStatus.CALCULATED:
            base["f1_published_total"] = f1_replay_result.published_total

    raw = Decimal(str(osa_decision.adaptive_adjustment_eur_per_min))
    if not raw.is_finite() or raw < 0:
        raise ValueError("OSA raw adjustment must be finite and non-negative")
    if osa_decision.status is OsaDecisionStatus.ACTIVE and raw <= 0:
        raise ValueError("Active OSA decision requires positive raw adjustment")
    if osa_decision.status is OsaDecisionStatus.INACTIVE and raw != 0:
        raise ValueError("Inactive OSA decision requires zero raw adjustment")
    effective = raw * intensity * rollout
    driver = ResponseDriverPoint(
        entity_id=entity_id,
        effective_at_utc=evaluation_time_utc,
        driver_name=RELEASE_DRIVER_NAME,
        driver_unit=RELEASE_DRIVER_UNIT,
        value=float(effective),
    )
    status = CompositionStatus.ACTIVE if effective > 0 else CompositionStatus.INACTIVE
    if rollout == 0:
        reason = "rollout_inactive"
    elif intensity == 0:
        reason = "price_intensity_zero"
    elif raw == 0:
        reason = f"osa_inactive:{osa_decision.reason_code}"
    else:
        reason = "adaptive_tariff_active"
    result = AdaptiveTariffComposition(
        **base,
        status=status,
        reason_code=reason,
        raw_adjustment_eur_per_min=raw,
        effective_policy_adjustment_eur_per_min=effective,
        counterfactual_time_component_eur_per_hour=effective * 60,
        response_driver=driver,
    )
    result.validate()
    return result


def _withheld(base, reason):
    result = AdaptiveTariffComposition(
        **base,
        status=CompositionStatus.WITHHELD,
        reason_code=reason,
        raw_adjustment_eur_per_min=None,
        effective_policy_adjustment_eur_per_min=None,
        counterfactual_time_component_eur_per_hour=None,
        response_driver=None,
    )
    result.validate()
    return result
