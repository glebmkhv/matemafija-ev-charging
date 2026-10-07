import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.database_v2 import (
    _ocpi_utc_text,
    _quality_for_ocpi_timestamp,
    save_datex_dynamic_publication,
    save_datex_static_publication,
    save_ocpi_credentials_metadata,
    save_ocpi_locations_snapshot,
    save_ocpi_tariffs_snapshot,
)
from src.datex import parse_dynamic_publication, parse_static_publication


OCPI_LOCATION = {
    "country_code": "LT",
    "party_id": "TEST",
    "id": "1",
    "publish": True,
    "name": "Test station",
    "address": "Test street 1",
    "city": "Vilnius",
    "country": "LTU",
    "coordinates": {"latitude": "54.680000", "longitude": "25.280000"},
    "operator": {"name": "Test operator", "website": "https://example.test"},
    "owner": {"name": "Test owner"},
    "facilities": ["PARKING_LOT"],
    "directions": [{"language": "en", "text": "Enter from the north"}],
    "opening_times": {
        "twentyfourseven": False,
        "regular_hours": [{"weekday": 1, "period_begin": "08:00", "period_end": "18:00"}],
    },
    "energy_mix": [{"source": "GENERAL_GREEN", "percentage": "100"}],
    "last_updated": "2026-10-06T10:00:00+00:00",
    "evses": [{
        "uid": "10",
        "evse_id": "TEST-E10-A",
        "status": "AVAILABLE",
        "capabilities": ["RFID_READER"],
        "last_updated": "2026-10-06T10:00:00+00:00",
        "connectors": [{
            "id": "1",
            "standard": "IEC_62196_T2",
            "format": "SOCKET",
            "power_type": "AC_3_PHASE",
            "voltage": 400,
            "amperage": 32,
            "max_electric_power": 22000,
            "tariff_ids": ["T1"],
            "last_updated": "2026-10-06T10:00:00+00:00",
        }],
    }],
}

OCPI_TARIFF = {
    "country_code": "LT",
    "party_id": "TEST",
    "id": "T1",
    "currency": "EUR",
    "elements": [{
        "price_components": [{
            "type": "ENERGY",
            "price": "0.3000",
            "step_size": 1,
            "vat": "21.0000",
        }],
        "restrictions": {"day_of_week": ["MONDAY"]},
    }],
    "last_updated": "2026-10-06T10:00:00+00:00",
}

STATIC_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<d2:payload xmlns:d2="https://datex2.eu/schema/3/d2Payload"
 xmlns:com="https://datex2.eu/schema/3/common"
 xmlns:egi="https://datex2.eu/schema/3/energyInfrastructure"
 xmlns:fac="https://datex2.eu/schema/3/facilities"
 xmlns:loc="https://datex2.eu/schema/3/locationReferencing"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xsi:type="egi:EnergyInfrastructureTablePublication" lang="lt" modelBaseVersion="3">
 <com:publicationTime>2026-10-06T13:00:00+03:00</com:publicationTime>
 <com:publicationCreator><com:country>lt</com:country><com:nationalIdentifier>lakd</com:nationalIdentifier></com:publicationCreator>
 <egi:energyInfrastructureTable id="EGI-T-1" version="v1">
  <egi:energyInfrastructureSite id="EGI-S-1" version="v1">
   <egi:energyInfrastructureStation id="EGI-ST-1" version="v1">
    <egi:lastUpdated>2026-10-06T12:50:00+03:00</egi:lastUpdated>
    <egi:energyProvider xsi:type="fac:OrganisationSpecification">
     <fac:lastUpdated>2026-10-06T12:00:00+03:00</fac:lastUpdated>
     <fac:name><com:values><com:value lang="lt">Test operator</com:value></com:values></fac:name>
     <fac:description><com:values><com:value lang="lt">Provider description</com:value></com:values></fac:description>
     <fac:linkToGeneralInformation>https://example.test</fac:linkToGeneralInformation>
     <fac:telephoneNumber>+37000000000</fac:telephoneNumber>
    </egi:energyProvider>
    <egi:siteLocation xsi:type="loc:LocationReference"><loc:pointByCoordinates><loc:pointCoordinates><loc:latitude>54.680000</loc:latitude><loc:longitude>25.280000</loc:longitude></loc:pointCoordinates></loc:pointByCoordinates></egi:siteLocation>
    <egi:numberOfRefillPoints>1</egi:numberOfRefillPoints>
    <egi:refillPoint xsi:type="egi:ElectricChargingPoint" id="LT-TEST-E10" version="v1">
     <egi:usageType>electricVehicle</egi:usageType>
     <egi:connector><egi:connectorType>Type 2</egi:connectorType><egi:maxPowerAtSocket>22</egi:maxPowerAtSocket></egi:connector>
    </egi:refillPoint>
    <egi:electricEnergyMix energyMixIndex="0"><egi:rates xsi:type="fac:RatesByReference">
     <fac:applicableCurrency>EUR</fac:applicableCurrency>
     <fac:overallPeriod><com:overallStartTime>2026-01-01T00:00:00+02:00</com:overallStartTime><com:validPeriod><com:periodName><com:values><com:value lang="en">monday</com:value></com:values></com:periodName><com:recurringTimePeriodOfDay><com:startTimeOfPeriod>00:00:00+0300</com:startTimeOfPeriod><com:endTimeOfPeriod>23:59:59+0300</com:endTimeOfPeriod></com:recurringTimePeriodOfDay><com:recurringDayWeekMonthPeriod><com:applicableDay>monday</com:applicableDay></com:recurringDayWeekMonthPeriod></com:validPeriod></fac:overallPeriod>
     <fac:energyPricingPolicy><egi:pricingPolicy>pricePerDeliveryUnit</egi:pricingPolicy><egi:additionalInformation><com:values><com:value lang="lt">0.30 EUR/kWh</com:value></com:values></egi:additionalInformation></fac:energyPricingPolicy>
    </egi:rates></egi:electricEnergyMix>
   </egi:energyInfrastructureStation>
  </egi:energyInfrastructureSite>
 </egi:energyInfrastructureTable>
</d2:payload>'''

DYNAMIC_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<d2:payload xmlns:d2="https://datex2.eu/schema/3/d2Payload"
 xmlns:com="https://datex2.eu/schema/3/common"
 xmlns:egi="https://datex2.eu/schema/3/energyInfrastructure"
 xmlns:fac="https://datex2.eu/schema/3/facilities"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xsi:type="egi:EnergyInfrastructureStatusPublication" lang="lt" modelBaseVersion="3">
 <com:publicationTime>2026-10-06T13:05:00+03:00</com:publicationTime>
 <com:publicationCreator><com:country>lt</com:country><com:nationalIdentifier>lakd</com:nationalIdentifier></com:publicationCreator>
 <egi:energyInfrastructureSiteStatus id="EGI-S-1" version="v1">
  <fac:lastUpdated>2026-10-06T13:04:00+03:00</fac:lastUpdated>
  <egi:energyInfrastructureStationStatus id="EGI-ST-1" version="v1">
   <egi:isAvailable>true</egi:isAvailable>
   <egi:refillPointStatus id="0" connectorIndex="1"><egi:status>AVAILABLE</egi:status></egi:refillPointStatus>
  </egi:energyInfrastructureStationStatus>
 </egi:energyInfrastructureSiteStatus>
</d2:payload>'''


class DatabaseV2Test(unittest.TestCase):
    def test_timezone_naive_ocpi_timestamp_uses_vilnius_local_time(self):
        self.assertEqual(
            _ocpi_utc_text("2026-10-06T14:06:30"),
            "2026-10-06T11:06:30+00:00",
        )
        age, quality = _quality_for_ocpi_timestamp(
            "2026-10-06T14:06:30",
            "2026-10-06T12:48:39+00:00",
        )
        self.assertEqual(age, 6129.0)
        self.assertEqual(quality, "current_timezone_assumed_europe_vilnius")

    def test_ocpi_timestamp_with_offset_keeps_its_explicit_timezone(self):
        self.assertEqual(
            _ocpi_utc_text("2026-10-06T14:06:30+02:00"),
            "2026-10-06T12:06:30+00:00",
        )
        _, quality = _quality_for_ocpi_timestamp(
            "2026-10-06T14:06:30+02:00",
            "2026-10-06T12:48:39+00:00",
        )
        self.assertEqual(quality, "current")

    def test_complete_source_layers_history_and_mappings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "database.db"
            save_ocpi_locations_snapshot(
                [OCPI_LOCATION], path, "2026-10-06T10:01:00+00:00", "ocpi-location-1"
            )
            save_ocpi_tariffs_snapshot(
                [OCPI_TARIFF], path, "2026-10-06T10:01:01+00:00", "ocpi-tariff-1"
            )
            save_ocpi_credentials_metadata(
                {
                    "token": "must-not-be-stored",
                    "url": "https://example.test/ocpi",
                    "roles": [{
                        "role": "CPO",
                        "country_code": "LT",
                        "party_id": "TEST",
                        "business_details": {"name": "Test operator"},
                    }],
                },
                path,
                "2026-10-06T10:01:02+00:00",
                "ocpi-credentials-1",
            )
            save_datex_static_publication(
                parse_static_publication(STATIC_XML), STATIC_XML, path,
                "2026-10-06T10:02:00+00:00", "datex-static-1"
            )
            save_datex_dynamic_publication(
                parse_dynamic_publication(DYNAMIC_XML), DYNAMIC_XML, path,
                "2026-10-06T10:05:01+00:00", "datex-dynamic-1"
            )

            connection = sqlite3.connect(path)
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "collection_runs", "ocpi_locations", "ocpi_evses",
                    "ocpi_connectors", "ocpi_tariffs",
                    "datex_energy_infrastructure_stations",
                    "datex_refill_points", "datex_connectors",
                    "datex_refill_point_status_observations",
                    "charging_site_source_links",
                    "charging_equipment_source_links",
                )
            }
            raw_encoding = connection.execute(
                "SELECT DISTINCT content_encoding FROM raw_payloads"
            ).fetchall()
            mapping = connection.execute(
                "SELECT mapping_method, confidence_score FROM datex_dynamic_status_static_mappings"
            ).fetchone()
            credentials_raw = connection.execute(
                "SELECT sanitized_raw_json FROM ocpi_credentials_metadata"
            ).fetchone()[0]
            foreign_key_errors = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            connection.close()

            self.assertEqual(counts["collection_runs"], 5)
            self.assertEqual(counts["ocpi_locations"], 1)
            self.assertEqual(counts["datex_connectors"], 1)
            self.assertEqual(counts["datex_refill_point_status_observations"], 1)
            self.assertGreaterEqual(counts["charging_site_source_links"], 2)
            self.assertGreaterEqual(counts["charging_equipment_source_links"], 2)
            self.assertEqual(raw_encoding, [("gzip",)])
            self.assertEqual(mapping, ("equal_connector_count_and_ordinal", 0.7))
            self.assertNotIn("must-not-be-stored", credentials_raw)
            self.assertIn("[REDACTED]", credentials_raw)
            self.assertEqual(foreign_key_errors, [])

    def test_complete_snapshot_marks_missing_entity_without_deleting_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "database.db"
            save_ocpi_locations_snapshot(
                [OCPI_LOCATION], path, "2026-10-06T10:01:00+00:00", "run-1"
            )
            save_ocpi_locations_snapshot(
                [], path, "2026-10-06T10:06:00+00:00", "run-2"
            )
            connection = sqlite3.connect(path)
            current, missing_since = connection.execute(
                "SELECT is_current, missing_since FROM ocpi_evses"
            ).fetchone()
            observations = connection.execute(
                "SELECT COUNT(*) FROM ocpi_evse_status_observations"
            ).fetchone()[0]
            connection.close()
            self.assertEqual(current, 0)
            self.assertEqual(missing_since, "2026-10-06T10:06:00+00:00")
            self.assertEqual(observations, 1)


if __name__ == "__main__":
    unittest.main()
