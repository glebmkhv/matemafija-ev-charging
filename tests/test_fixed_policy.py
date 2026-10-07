import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.fixed_policy import ChargingSessionUsage, ReplayStatus, UsageSlice, fixed_policy_specification, replay_observed_tariff

SCHEMA = """
CREATE TABLE ocpi_connector_tariff_assignments (ocpi_connector_key TEXT, ocpi_tariff_key TEXT, valid_from TEXT, valid_to TEXT);
CREATE TABLE ocpi_tariffs (ocpi_tariff_key TEXT PRIMARY KEY, currency TEXT, tax_included_raw TEXT, minimum_price_raw TEXT, maximum_price_raw TEXT, start_date_time_raw TEXT, end_date_time_raw TEXT, current_revision_id INTEGER, source_last_updated_utc TEXT);
CREATE TABLE source_entity_revisions (source_entity_revision_id INTEGER, source_entity_type TEXT, source_entity_key TEXT, created_at TEXT);
CREATE TABLE ocpi_tariff_elements (source_entity_revision_id INTEGER, tariff_element_index INTEGER);
CREATE TABLE ocpi_tariff_price_components (source_entity_revision_id INTEGER, tariff_element_index INTEGER, price_component_index INTEGER, component_type TEXT, price_decimal TEXT, step_size INTEGER, vat_percentage_decimal TEXT);
CREATE TABLE ocpi_tariff_restrictions (source_entity_revision_id INTEGER, tariff_element_index INTEGER, start_time TEXT, end_time TEXT, start_date TEXT, end_date TEXT, minimum_energy_kwh REAL, maximum_energy_kwh REAL, minimum_power_kw REAL, maximum_power_kw REAL, minimum_duration_seconds INTEGER, maximum_duration_seconds INTEGER, reservation_restriction TEXT);
CREATE TABLE ocpi_tariff_restriction_days (source_entity_revision_id INTEGER, tariff_element_index INTEGER, day_index INTEGER, day_of_week TEXT);
CREATE TABLE ocpi_tariff_alternative_texts (source_entity_revision_id INTEGER, alternative_text_index INTEGER, alternative_text TEXT);
CREATE TABLE ocpi_connectors (ocpi_connector_key TEXT, ocpi_evse_key TEXT);
CREATE TABLE ocpi_evses (ocpi_evse_key TEXT, ocpi_location_key TEXT);
CREATE TABLE charging_site_source_links (charging_site_id TEXT, source_system TEXT, source_entity_type TEXT, source_entity_key TEXT, is_current INTEGER);
CREATE TABLE charging_sites (charging_site_id TEXT);
CREATE TABLE datex_energy_infrastructure_stations (datex_station_key TEXT);
CREATE TABLE datex_electric_energy_mixes (datex_energy_mix_key TEXT, datex_station_key TEXT);
CREATE TABLE datex_rates (datex_rate_key TEXT, datex_energy_mix_key TEXT, applicable_currency TEXT, overall_start_time_raw TEXT);
CREATE TABLE datex_energy_pricing_policies (datex_pricing_policy_key TEXT, datex_rate_key TEXT, pricing_policy_canonical TEXT);
CREATE TABLE datex_pricing_additional_information (datex_pricing_policy_key TEXT, text_index INTEGER, raw_text TEXT);
CREATE TABLE datex_rate_valid_periods (datex_rate_key TEXT, period_ordinal INTEGER, start_time_of_period_raw TEXT, end_time_of_period_raw TEXT, applicable_day_canonical TEXT, xml_namespace_status TEXT);
"""


def database():
    db=sqlite3.connect(":memory:"); db.executescript(SCHEMA)
    db.execute("INSERT INTO ocpi_connector_tariff_assignments VALUES ('c1','t1','2026-01-01T00:00:00+00:00',NULL)")
    db.execute("INSERT INTO ocpi_tariffs VALUES ('t1','EUR','NO',NULL,NULL,NULL,NULL,1,'2026-01-01T00:00:00+00:00')")
    db.execute("INSERT INTO source_entity_revisions VALUES (1,'ocpi_tariff','t1','2026-01-01T00:00:00+00:00')")
    db.executemany("INSERT INTO ocpi_tariff_elements VALUES (1,?)",[(0,),(1,)])
    db.executemany("INSERT INTO ocpi_tariff_price_components VALUES (1,?,?,?,?,?,?)",[
        (0,0,'FLAT','0.30',1,'21'),(0,1,'ENERGY','0.40',100,'21'),
        (1,0,'PARKING_TIME','3.00',300,'21')])
    db.execute("INSERT INTO ocpi_tariff_restrictions VALUES (1,1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,3500,NULL,NULL)")
    db.execute("INSERT INTO ocpi_connectors VALUES ('c1','e1')"); db.execute("INSERT INTO ocpi_evses VALUES ('e1','l1')")
    db.executemany("INSERT INTO charging_site_source_links VALUES (?,?,?,?,1)",[
        ('s1','OCPI','OCPI_LOCATION','l1'),('s1','DATEX_II','DATEX_STATION','d1')])
    db.execute("INSERT INTO charging_sites VALUES ('s1')"); db.execute("INSERT INTO datex_energy_infrastructure_stations VALUES ('d1')")
    db.execute("INSERT INTO datex_electric_energy_mixes VALUES ('m1','d1')")
    db.execute("INSERT INTO datex_rates VALUES ('r1','m1','EUR','2025-01-01T00:00:00+02:00')")
    db.execute("INSERT INTO datex_energy_pricing_policies VALUES ('p1','r1','priceperdeliveryunit')")
    db.execute("INSERT INTO datex_pricing_additional_information VALUES ('p1',0,'0.3 € + 0.4 €/kWh + 3 €/val. parkavimo mokestis')")
    return db


def usage(parking=1000):
    start=datetime(2026,5,4,10,tzinfo=timezone.utc)
    return ChargingSessionUsage('c1',start,start+timedelta(hours=1),(
        UsageSlice(start,start+timedelta(hours=1),Decimal('10.01'),2600,parking,Decimal('11')),))


class ObservedTariffReplayTest(unittest.TestCase):
    def test_composite_tariff_steps_vat_and_datex(self):
        result=replay_observed_tariff(database(),usage())
        self.assertEqual(result.status,ReplayStatus.CALCULATED)
        self.assertEqual([x.component_type for x in result.lines],['ENERGY','PARKING_TIME','FLAT'])
        self.assertEqual(result.lines[0].billed_quantity,Decimal('10.1'))
        self.assertEqual(result.lines[1].billed_quantity,Decimal('0.3333333333333333333333333333'))
        self.assertEqual(result.published_total,Decimal('5.340000000000000000000000000'))
        self.assertEqual(result.total_including_vat,result.published_total*Decimal('1.21'))
        self.assertEqual(result.datex_evidence[0].parsed_energy_prices_per_kwh,(Decimal('0.4'),))
        self.assertEqual(result.datex_evidence[0].parsed_parking_prices_per_hour,(Decimal('3'),))
        self.assertEqual(result.datex_price_signal_check,'numeric_overlap_found')

    def test_duration_restriction_excludes_parking(self):
        result=replay_observed_tariff(database(),usage(600))
        self.assertNotIn('PARKING_TIME',[x.component_type for x in result.lines])

    def test_missing_assignment_is_withheld(self):
        item=usage(); missing=ChargingSessionUsage('missing',item.session_start_utc,item.session_end_utc,item.periods)
        result=replay_observed_tariff(database(),missing)
        self.assertEqual(result.status,ReplayStatus.WITHHELD)

    def test_tariff_minimum_price_is_applied_and_auditable(self):
        db=database(); db.execute("UPDATE ocpi_tariffs SET minimum_price_raw='\"6.00\"'")
        result=replay_observed_tariff(db,usage())
        self.assertEqual(result.published_total,Decimal('6.00'))
        self.assertEqual(result.lines[-1].component_type,'MINIMUM_PRICE_ADJUSTMENT')

    def test_contract_has_only_observed_tariff_baseline(self):
        policy=fixed_policy_specification(); policy.validate()
        self.assertEqual(policy.policy_id,'observed_tariff_replay')
        self.assertEqual(policy.parameters['source_of_charge'],'OCPI')


if __name__=='__main__': unittest.main()
