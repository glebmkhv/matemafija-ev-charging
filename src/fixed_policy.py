"""Replay the tariff actually published for an OCPI connector.

OCPI is authoritative for billing. Matched DATEX II pricing is retained as
corroborating evidence and is never added to the OCPI bill.
"""
from __future__ import annotations

import re
import sqlite3
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING
from enum import Enum
from zoneinfo import ZoneInfo

try:
    from .simulation_contract import (
        ObservedChargingPeriod as UsageSlice,
        ObservedChargingSession as ChargingSessionUsage,
        PolicyKind, PolicySpecification,
    )
except ImportError:  # pragma: no cover
    from simulation_contract import (
        ObservedChargingPeriod as UsageSlice,
        ObservedChargingSession as ChargingSessionUsage,
        PolicyKind, PolicySpecification,
    )

POLICY_ID = "observed_tariff_replay"
POLICY_VERSION = "1.0.0"
DIMENSIONS = ("ENERGY", "TIME", "PARKING_TIME", "FLAT")


class ReplayStatus(str, Enum):
    CALCULATED = "calculated"
    WITHHELD = "withheld"


@dataclass(frozen=True)
class TariffRestriction:
    start_time: time | None = None
    end_time: time | None = None
    start_date: date | None = None
    end_date: date | None = None
    minimum_energy_kwh: Decimal | None = None
    maximum_energy_kwh: Decimal | None = None
    minimum_power_kw: Decimal | None = None
    maximum_power_kw: Decimal | None = None
    minimum_duration_seconds: int | None = None
    maximum_duration_seconds: int | None = None
    reservation_restriction: str | None = None
    days_of_week: tuple[str, ...] = ()


@dataclass(frozen=True)
class TariffComponent:
    component_type: str
    price: Decimal
    step_size: int
    vat_percentage: Decimal | None = None

    def validate(self):
        if self.component_type not in DIMENSIONS:
            raise ValueError(f"Unsupported OCPI tariff dimension: {self.component_type}")
        if self.price < 0 or self.step_size <= 0:
            raise ValueError("Tariff price must be non-negative and step_size positive")


@dataclass(frozen=True)
class TariffElement:
    index: int
    components: tuple[TariffComponent, ...]
    restriction: TariffRestriction | None = None


@dataclass(frozen=True)
class ObservedTariff:
    tariff_key: str
    revision_id: int
    currency: str
    tax_included: bool | None
    minimum_price: Decimal | None
    maximum_price: Decimal | None
    valid_from: datetime | None
    valid_to: datetime | None
    elements: tuple[TariffElement, ...]
    source_last_updated_utc: str | None
    alternative_texts: tuple[str, ...] = ()


@dataclass(frozen=True)
class DatexTariffEvidence:
    charging_site_id: str
    station_key: str
    rate_key: str
    currency: str | None
    pricing_policy: str | None
    overall_start_time_raw: str | None
    valid_periods: tuple[dict, ...]
    published_texts: tuple[str, ...]
    parsed_energy_prices_per_kwh: tuple[Decimal, ...]
    parsed_flat_prices: tuple[Decimal, ...]
    parsed_parking_prices_per_hour: tuple[Decimal, ...]


@dataclass(frozen=True)
class TariffChargeLine:
    component_type: str
    tariff_element_index: int
    price_per_unit: Decimal
    unit: str
    measured_quantity: Decimal
    billed_quantity: Decimal
    step_size: int
    published_cost: Decimal
    vat_percentage: Decimal | None
    cost_including_vat: Decimal | None


@dataclass(frozen=True)
class TariffReplayResult:
    policy_id: str
    policy_version: str
    status: ReplayStatus
    connector_key: str
    tariff_key: str | None
    tariff_revision_id: int | None
    currency: str | None
    tax_included: bool | None
    published_total: Decimal | None
    total_including_vat: Decimal | None
    lines: tuple[TariffChargeLine, ...]
    datex_evidence: tuple[DatexTariffEvidence, ...]
    datex_price_signal_check: str
    reason_codes: tuple[str, ...]

    def as_record(self):
        def convert(value):
            if isinstance(value, Decimal): return str(value)
            if isinstance(value, Enum): return value.value
            if isinstance(value, tuple): return [convert(x) for x in value]
            if isinstance(value, dict): return {k: convert(v) for k, v in value.items()}
            return value
        return convert(asdict(self))


def fixed_policy_specification():
    return PolicySpecification(
        policy_id=POLICY_ID, policy_version=POLICY_VERSION, kind=PolicyKind.FIXED,
        parameters={"source_of_charge": "OCPI", "datex_role": "corroborating_evidence_only",
                    "supported_dimensions": ",".join(DIMENSIONS),
                    "requires_observed_session_usage": True},
        decision_interval_minutes=1, currency="SOURCE_DEFINED")


def _dt(value):
    if not value: return None
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=ZoneInfo("Europe/Vilnius"))


def _time(value): return time.fromisoformat(value) if value else None
def _dec(value): return None if value is None else Decimal(str(value))


def _tax(value):
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized in {"YES", "TRUE", "1"}: return True
    if normalized in {"NO", "FALSE", "0"}: return False
    return None


def _raw_price(value):
    if value in (None, "", "null"): return None
    try: value=json.loads(value)
    except (json.JSONDecodeError, TypeError): pass
    return None if value is None else Decimal(str(value))


def load_observed_tariff(connection: sqlite3.Connection, connector_key: str,
                         observed_at: datetime) -> ObservedTariff | None:
    """Resolve connector assignment and the tariff revision known at a time."""
    if observed_at.tzinfo is None: raise ValueError("observed_at must include a timezone")
    instant = observed_at.isoformat()
    assignment = connection.execute(
        "SELECT ocpi_tariff_key FROM ocpi_connector_tariff_assignments "
        "WHERE ocpi_connector_key=? AND valid_from<=? AND (valid_to IS NULL OR valid_to>?) "
        "ORDER BY valid_from DESC LIMIT 1", (connector_key, instant, instant)).fetchone()
    if not assignment: return None
    key = assignment[0]
    row = connection.execute(
        "SELECT currency,tax_included_raw,minimum_price_raw,maximum_price_raw,"
        "start_date_time_raw,end_date_time_raw,current_revision_id,source_last_updated_utc "
        "FROM ocpi_tariffs WHERE ocpi_tariff_key=?",
        (key,)).fetchone()
    if not row: return None
    historical = connection.execute(
        "SELECT source_entity_revision_id FROM source_entity_revisions "
        "WHERE source_entity_type='ocpi_tariff' AND source_entity_key=? AND created_at<=? "
        "ORDER BY created_at DESC LIMIT 1", (key, instant)).fetchone()
    revision = historical[0] if historical else row[6]
    elements = []
    indices = connection.execute(
        "SELECT tariff_element_index FROM ocpi_tariff_elements "
        "WHERE source_entity_revision_id=? ORDER BY tariff_element_index", (revision,)).fetchall()
    for (index,) in indices:
        components = tuple(TariffComponent(r[0], Decimal(r[1]), r[2], _dec(r[3])) for r in
            connection.execute("SELECT component_type,price_decimal,step_size,vat_percentage_decimal "
            "FROM ocpi_tariff_price_components WHERE source_entity_revision_id=? "
            "AND tariff_element_index=? ORDER BY price_component_index", (revision,index)))
        rr = connection.execute("SELECT start_time,end_time,start_date,end_date,minimum_energy_kwh,"
            "maximum_energy_kwh,minimum_power_kw,maximum_power_kw,minimum_duration_seconds,"
            "maximum_duration_seconds,reservation_restriction FROM ocpi_tariff_restrictions "
            "WHERE source_entity_revision_id=? AND tariff_element_index=?", (revision,index)).fetchone()
        restriction = None
        if rr:
            days = tuple(r[0].upper() for r in connection.execute(
                "SELECT day_of_week FROM ocpi_tariff_restriction_days WHERE source_entity_revision_id=? "
                "AND tariff_element_index=? ORDER BY day_index", (revision,index)) if r[0])
            restriction = TariffRestriction(_time(rr[0]),_time(rr[1]),date.fromisoformat(rr[2]) if rr[2] else None,
                date.fromisoformat(rr[3]) if rr[3] else None,_dec(rr[4]),_dec(rr[5]),_dec(rr[6]),_dec(rr[7]),
                rr[8],rr[9],rr[10],days)
        for component in components: component.validate()
        elements.append(TariffElement(index, components, restriction))
    texts = tuple(r[0] for r in connection.execute("SELECT alternative_text FROM ocpi_tariff_alternative_texts "
        "WHERE source_entity_revision_id=? ORDER BY alternative_text_index", (revision,)) if r[0])
    return ObservedTariff(key, revision, row[0], _tax(row[1]), _raw_price(row[2]),
                          _raw_price(row[3]), _dt(row[4]), _dt(row[5]),
                          tuple(elements), row[7], texts)


_ENERGY_RE = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)?)\s*€?\s*/\s*kwh", re.I)
_PARK_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*€?\s*/\s*val\.?\s*parkavimo", re.I)
_FLAT_RE = re.compile(r"(?<![/\d.])(\d+(?:[.,]\d+)?)\s*€\s*\+", re.I)


def _prices(pattern, texts):
    return tuple(sorted({Decimal(x.replace(",", ".")) for text in texts for x in pattern.findall(text)}))


def load_datex_tariff_evidence(connection: sqlite3.Connection, connector_key: str,
                               observed_at: datetime) -> tuple[DatexTariffEvidence, ...]:
    """Load all DATEX pricing for physical stations matched to the OCPI site."""
    rows = connection.execute("""SELECT DISTINCT cs.charging_site_id,ds.datex_station_key,
        dr.datex_rate_key,dr.applicable_currency,dp.pricing_policy_canonical,dr.overall_start_time_raw
        FROM ocpi_connectors c JOIN ocpi_evses e ON e.ocpi_evse_key=c.ocpi_evse_key
        JOIN charging_site_source_links ol ON ol.source_system='OCPI'
          AND ol.source_entity_type='OCPI_LOCATION' AND ol.source_entity_key=e.ocpi_location_key AND ol.is_current=1
        JOIN charging_sites cs ON cs.charging_site_id=ol.charging_site_id
        JOIN charging_site_source_links dl ON dl.charging_site_id=cs.charging_site_id
          AND dl.source_system='DATEX_II' AND dl.source_entity_type='DATEX_STATION' AND dl.is_current=1
        JOIN datex_energy_infrastructure_stations ds ON ds.datex_station_key=dl.source_entity_key
        JOIN datex_electric_energy_mixes em ON em.datex_station_key=ds.datex_station_key
        JOIN datex_rates dr ON dr.datex_energy_mix_key=em.datex_energy_mix_key
        LEFT JOIN datex_energy_pricing_policies dp ON dp.datex_rate_key=dr.datex_rate_key
        WHERE c.ocpi_connector_key=?""", (connector_key,)).fetchall()
    result=[]
    for site,station,rate,currency,policy,start_raw in rows:
        if _dt(start_raw) and _dt(start_raw)>observed_at: continue
        periods=tuple(dict(zip(("start_time","end_time","day","namespace_status"),r)) for r in
            connection.execute("SELECT start_time_of_period_raw,end_time_of_period_raw,"
            "applicable_day_canonical,xml_namespace_status FROM datex_rate_valid_periods "
            "WHERE datex_rate_key=? ORDER BY period_ordinal",(rate,)))
        texts=tuple(r[0] for r in connection.execute("SELECT i.raw_text FROM datex_energy_pricing_policies p "
            "JOIN datex_pricing_additional_information i USING(datex_pricing_policy_key) "
            "WHERE p.datex_rate_key=? ORDER BY i.text_index",(rate,)) if r[0])
        flat_prices=_prices(_FLAT_RE,texts)
        if policy=="free" and not flat_prices: flat_prices=(Decimal("0"),)
        result.append(DatexTariffEvidence(site,station,rate,currency,policy,start_raw,periods,texts,
            _prices(_ENERGY_RE,texts),flat_prices,_prices(_PARK_RE,texts)))
    return tuple(result)


def _datex_signal_check(lines, evidence, currency):
    if not evidence: return "no_matched_datex"
    comparable=[item for item in evidence if item.currency in (None,currency)]
    if not comparable: return "currency_not_comparable"
    source={"ENERGY":set(),"FLAT":set(),"PARKING_TIME":set()}
    for item in comparable:
        source["ENERGY"].update(item.parsed_energy_prices_per_kwh)
        source["FLAT"].update(item.parsed_flat_prices)
        source["PARKING_TIME"].update(item.parsed_parking_prices_per_hour)
    compared=False
    for line in lines:
        if line.component_type in source and source[line.component_type]:
            compared=True
            if line.price_per_unit in source[line.component_type]: return "numeric_overlap_found"
    return "no_numeric_overlap" if compared else "no_comparable_numeric_signal"


def _clock_matches(dt, restriction):
    if restriction.start_date and dt.date()<restriction.start_date: return False
    if restriction.end_date and dt.date()>=restriction.end_date: return False
    if restriction.days_of_week and dt.strftime("%A").upper() not in restriction.days_of_week: return False
    current=dt.timetz().replace(tzinfo=None); start=restriction.start_time; end=restriction.end_time
    if start and end: return start<=current<end if start<=end else current>=start or current<end
    if start and current<start: return False
    if end and current>=end: return False
    return True


def _matches(r,dt,energy,power,duration,reservation):
    if r is None: return True
    if not _clock_matches(dt,r): return False
    checks=((r.minimum_energy_kwh,energy,lambda a,b:b>=a),(r.maximum_energy_kwh,energy,lambda a,b:b<a),
            (r.minimum_power_kw,power,lambda a,b:b>=a),(r.maximum_power_kw,power,lambda a,b:b<a),
            (r.minimum_duration_seconds,duration,lambda a,b:b>=a),
            (r.maximum_duration_seconds,duration,lambda a,b:b<a))
    if any(bound is not None and (value is None or not test(bound,value)) for bound,value,test in checks): return False
    return not r.reservation_restriction or reservation==r.reservation_restriction


def _component(tariff,dimension,dt,energy,power,duration,reservation):
    for element in tariff.elements:
        found=next((x for x in element.components if x.component_type==dimension),None)
        if found and _matches(element.restriction,dt,energy,power,duration,reservation): return element.index,found
    return None


def _ceil(value,step):
    return value if value==0 else (value/step).to_integral_value(rounding=ROUND_CEILING)*step


def _vat(cost,component,tax_included):
    if tax_included is True: return cost
    if tax_included is False and component.vat_percentage is not None:
        return cost*(Decimal("1")+component.vat_percentage/Decimal("100"))
    return None


def replay_observed_tariff(connection: sqlite3.Connection, usage: ChargingSessionUsage,
                           local_timezone="Europe/Vilnius") -> TariffReplayResult:
    """Calculate the source-published tariff from observed session quantities."""
    usage.validate(); tariff=load_observed_tariff(connection,usage.connector_key,usage.session_start_utc)
    datex=load_datex_tariff_evidence(connection,usage.connector_key,usage.session_start_utc)
    base=dict(policy_id=POLICY_ID,policy_version=POLICY_VERSION,connector_key=usage.connector_key,datex_evidence=datex)
    if tariff is None:
        return TariffReplayResult(status=ReplayStatus.WITHHELD,tariff_key=None,tariff_revision_id=None,
            currency=None,tax_included=None,published_total=None,total_including_vat=None,lines=(),
            datex_price_signal_check=_datex_signal_check((),datex,None),
            reason_codes=("no_ocpi_tariff_assignment_at_session_start",),**base)
    if (tariff.valid_from and usage.session_start_utc<tariff.valid_from) or (tariff.valid_to and usage.session_start_utc>=tariff.valid_to):
        return TariffReplayResult(status=ReplayStatus.WITHHELD,tariff_key=tariff.tariff_key,
            tariff_revision_id=tariff.revision_id,currency=tariff.currency,tax_included=tariff.tax_included,
            published_total=None,total_including_vat=None,lines=(),
            datex_price_signal_check=_datex_signal_check((),datex,tariff.currency),
            reason_codes=("tariff_not_valid_at_session_start",),**base)
    zone=ZoneInfo(local_timezone); allocations={x:[] for x in DIMENSIONS}; energy=Decimal("0"); duration=0
    for period in usage.periods:
        energy+=period.energy_kwh; duration+=period.charging_seconds+period.parking_seconds
        local=period.start_utc.astimezone(zone)
        local_end=(period.end_utc-timedelta(microseconds=1)).astimezone(zone)
        if any(element.restriction and
               _clock_matches(local,element.restriction)!=_clock_matches(local_end,element.restriction)
               for element in tariff.elements):
            return TariffReplayResult(status=ReplayStatus.WITHHELD,tariff_key=tariff.tariff_key,
                tariff_revision_id=tariff.revision_id,currency=tariff.currency,tax_included=tariff.tax_included,
                published_total=None,total_including_vat=None,lines=(),
                datex_price_signal_check=_datex_signal_check((),datex,tariff.currency),
                reason_codes=("usage_slice_crosses_tariff_boundary_split_required",),**base)
        for dimension,quantity in (("ENERGY",period.energy_kwh),("TIME",Decimal(period.charging_seconds)),
                                   ("PARKING_TIME",Decimal(period.parking_seconds))):
            if not quantity: continue
            selected=_component(tariff,dimension,local,energy,period.average_power_kw,duration,usage.reservation_restriction)
            if selected: allocations[dimension].append((*selected,quantity))
        flat=_component(tariff,"FLAT",local,energy,period.average_power_kw,duration,usage.reservation_restriction)
        if flat and not any(x[0]==flat[0] for x in allocations["FLAT"]): allocations["FLAT"].append((*flat,Decimal("1")))
    lines=[]
    for dimension in DIMENSIONS:
        items=allocations[dimension]
        if not items: continue
        measured=sum((x[2] for x in items),Decimal("0")); last=items[-1][1]
        step=Decimal(last.step_size)/Decimal("1000") if dimension=="ENERGY" else Decimal(last.step_size)
        if dimension=="FLAT": step=Decimal("1")
        # OCPI applies time step_size once to TIME/PARKING_TIME together:
        # parking gets the rounding when it exists, otherwise charging time does.
        if dimension=="TIME" and allocations["PARKING_TIME"]:
            excess=Decimal("0")
        else:
            excess=_ceil(measured,step)-measured
        for i,(element,component,quantity) in enumerate(items):
            billed=quantity+(excess if i==len(items)-1 else Decimal("0"))
            divisor=Decimal("3600") if dimension in {"TIME","PARKING_TIME"} else Decimal("1")
            cost=billed/divisor*component.price
            lines.append(TariffChargeLine(dimension,element,component.price,
                "kWh" if dimension=="ENERGY" else ("hour" if dimension in {"TIME","PARKING_TIME"} else "session"),
                quantity/divisor,billed/divisor,component.step_size,cost,component.vat_percentage,
                _vat(cost,component,tariff.tax_included)))
    total=sum((x.published_cost for x in lines),Decimal("0"))
    if tariff.minimum_price is not None and total < tariff.minimum_price:
        adjustment=tariff.minimum_price-total; total=tariff.minimum_price
        lines.append(TariffChargeLine("MINIMUM_PRICE_ADJUSTMENT",-1,adjustment,"session",
            Decimal("1"),Decimal("1"),1,adjustment,None,
            adjustment if tariff.tax_included is True else None))
    if tariff.maximum_price is not None and total > tariff.maximum_price:
        adjustment=tariff.maximum_price-total; total=tariff.maximum_price
        lines.append(TariffChargeLine("MAXIMUM_PRICE_ADJUSTMENT",-1,adjustment,"session",
            Decimal("1"),Decimal("1"),1,adjustment,None,
            adjustment if tariff.tax_included is True else None))
    total_vat=sum((x.cost_including_vat for x in lines),Decimal("0")) if all(x.cost_including_vat is not None for x in lines) else None
    return TariffReplayResult(status=ReplayStatus.CALCULATED,tariff_key=tariff.tariff_key,
        tariff_revision_id=tariff.revision_id,currency=tariff.currency,tax_included=tariff.tax_included,
        published_total=total,total_including_vat=total_vat,lines=tuple(lines),
        datex_price_signal_check=_datex_signal_check(lines,datex,tariff.currency),
        reason_codes=("ocpi_tariff_replayed",),**base)
