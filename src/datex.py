"""Download and parse the Via Lietuva DATEX II energy publications."""

import xml.etree.ElementTree as ElementTree

import requests


STATIC_PUBLICATION_URL = (
    "https://ev.vialietuva.lt/publicdata/"
    "EnergyInfrastructureTablePublication"
)
DYNAMIC_PUBLICATION_URL = (
    "https://ev.vialietuva.lt/publicdata/"
    "EnergyInfrastructureStatusPublication"
)

NAMESPACES = {
    "common": "https://datex2.eu/schema/3/common",
    "energy": "https://datex2.eu/schema/3/energyInfrastructure",
    "facilities": "https://datex2.eu/schema/3/facilities",
    "location": "https://datex2.eu/schema/3/locationReferencing",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def download_datex_publication(url):
    """Return unmodified XML bytes together with HTTP metadata."""
    response = requests.get(url, timeout=(10, 120))
    response.raise_for_status()
    return {
        "requested_url": response.url,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type"),
        "payload_bytes": response.content,
    }


def fetch_static_publication():
    return download_datex_publication(STATIC_PUBLICATION_URL)


def fetch_dynamic_publication():
    return download_datex_publication(DYNAMIC_PUBLICATION_URL)


def _text(element, path, default=None):
    child = element.find(path, NAMESPACES)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _multilingual_values(element, path):
    return [
        {
            "language": value.get("lang"),
            "text": (value.text or "").strip(),
        }
        for value in element.findall(path, NAMESPACES)
    ]


def _publication_metadata(root):
    return {
        "publication_type": root.get(f"{{{NAMESPACES['xsi']}}}type"),
        "language": root.get("lang"),
        "model_base_version": root.get("modelBaseVersion"),
        "schema_location": root.get(
            f"{{{NAMESPACES['xsi']}}}schemaLocation"
        ),
        "feed_description": _text(root, "common:feedDescription"),
        "publication_time": _text(root, "common:publicationTime"),
        "publication_creator_country": _text(
            root, "common:publicationCreator/common:country"
        ),
        "publication_creator_national_identifier": _text(
            root,
            "common:publicationCreator/common:nationalIdentifier",
        ),
    }


def parse_static_publication(payload_bytes):
    """Parse every field currently present in the static publication."""
    root = ElementTree.fromstring(payload_bytes)
    result = _publication_metadata(root)
    table = root.find("energy:energyInfrastructureTable", NAMESPACES)
    if table is None:
        raise ValueError("DATEX static publication has no infrastructure table")

    parsed_table = {
        "id": table.get("id"),
        "version": table.get("version"),
        "sites": [],
    }
    for site in table.findall("energy:energyInfrastructureSite", NAMESPACES):
        parsed_site = {
            "id": site.get("id"),
            "version": site.get("version"),
            "stations": [],
        }
        for station in site.findall(
            "energy:energyInfrastructureStation", NAMESPACES
        ):
            provider = station.find("energy:energyProvider", NAMESPACES)
            provider_data = None
            if provider is not None:
                provider_data = {
                    "xsi_type": provider.get(
                        f"{{{NAMESPACES['xsi']}}}type"
                    ),
                    "last_updated": _text(
                        provider, "facilities:lastUpdated"
                    ),
                    "names": _multilingual_values(
                        provider,
                        "facilities:name/common:values/common:value",
                    ),
                    "descriptions": _multilingual_values(
                        provider,
                        "facilities:description/common:values/common:value",
                    ),
                    "link_to_general_information": _text(
                        provider, "facilities:linkToGeneralInformation"
                    ),
                    "telephone_number": _text(
                        provider, "facilities:telephoneNumber"
                    ),
                }

            site_location = station.find("energy:siteLocation", NAMESPACES)
            parsed_station = {
                "id": station.get("id"),
                "version": station.get("version"),
                "last_updated": _text(station, "energy:lastUpdated"),
                "energy_provider": provider_data,
                "site_location_xsi_type": (
                    site_location.get(f"{{{NAMESPACES['xsi']}}}type")
                    if site_location is not None else None
                ),
                "latitude": _text(station, ".//location:latitude"),
                "longitude": _text(station, ".//location:longitude"),
                "number_of_refill_points": _text(
                    station, "energy:numberOfRefillPoints"
                ),
                "refill_points": [],
                "electric_energy_mixes": [],
            }
            for refill_ordinal, refill_point in enumerate(
                station.findall("energy:refillPoint", NAMESPACES)
            ):
                parsed_refill_point = {
                    "id": refill_point.get("id"),
                    "version": refill_point.get("version"),
                    "xsi_type": refill_point.get(
                        f"{{{NAMESPACES['xsi']}}}type"
                    ),
                    "usage_type": _text(refill_point, "energy:usageType"),
                    "ordinal_within_station": refill_ordinal,
                    "connectors": [],
                }
                for connector_ordinal, connector in enumerate(
                    refill_point.findall("energy:connector", NAMESPACES)
                ):
                    parsed_refill_point["connectors"].append({
                        "connector_ordinal": connector_ordinal,
                        "connector_type": _text(
                            connector, "energy:connectorType"
                        ),
                        "max_power_at_socket": _text(
                            connector, "energy:maxPowerAtSocket"
                        ),
                    })
                parsed_station["refill_points"].append(parsed_refill_point)

            for mix_ordinal, energy_mix in enumerate(
                station.findall("energy:electricEnergyMix", NAMESPACES)
            ):
                parsed_mix = {
                    "energy_mix_index": energy_mix.get("energyMixIndex"),
                    "mix_ordinal": mix_ordinal,
                    "rates": [],
                }
                for rate_ordinal, rates in enumerate(
                    energy_mix.findall("energy:rates", NAMESPACES)
                ):
                    parsed_rates = {
                        "rate_ordinal": rate_ordinal,
                        "xsi_type": rates.get(
                            f"{{{NAMESPACES['xsi']}}}type"
                        ),
                        "applicable_currency": _text(
                            rates, "facilities:applicableCurrency"
                        ),
                        "overall_start_time": _text(
                            rates,
                            "facilities:overallPeriod/common:overallStartTime",
                        ),
                        "valid_periods": [],
                        "pricing_policy": None,
                    }
                    overall_period = rates.find(
                        "facilities:overallPeriod", NAMESPACES
                    )
                    if overall_period is not None:
                        periods = list(overall_period.findall(
                            "common:validPeriod", NAMESPACES
                        ))
                        periods.extend(overall_period.findall("validPeriod"))
                        for period_ordinal, period in enumerate(periods):
                            parsed_rates["valid_periods"].append({
                                "period_ordinal": period_ordinal,
                                "xml_namespace_status": (
                                    "datex_common_namespace"
                                    if period.tag.startswith("{")
                                    else "unqualified_namespace"
                                ),
                                "period_names": _multilingual_values(
                                    period,
                                    "common:periodName/common:values/common:value",
                                ),
                                "start_time_of_period": _text(
                                    period,
                                    "common:recurringTimePeriodOfDay/"
                                    "common:startTimeOfPeriod",
                                ),
                                "end_time_of_period": _text(
                                    period,
                                    "common:recurringTimePeriodOfDay/"
                                    "common:endTimeOfPeriod",
                                ),
                                "applicable_day": _text(
                                    period,
                                    "common:recurringDayWeekMonthPeriod/"
                                    "common:applicableDay",
                                ),
                            })
                    pricing_policy = rates.find(
                        "facilities:energyPricingPolicy", NAMESPACES
                    )
                    if pricing_policy is not None:
                        parsed_rates["pricing_policy"] = {
                            "pricing_policy": _text(
                                pricing_policy, "energy:pricingPolicy"
                            ),
                            "additional_information": _multilingual_values(
                                pricing_policy,
                                "energy:additionalInformation/"
                                "common:values/common:value",
                            ),
                        }
                    parsed_mix["rates"].append(parsed_rates)
                parsed_station["electric_energy_mixes"].append(parsed_mix)
            parsed_site["stations"].append(parsed_station)
        parsed_table["sites"].append(parsed_site)
    result["energy_infrastructure_table"] = parsed_table
    return result


def parse_dynamic_publication(payload_bytes):
    """Parse every field currently present in the dynamic publication."""
    root = ElementTree.fromstring(payload_bytes)
    result = _publication_metadata(root)
    result["table_reference"] = _text(root, "energy:tableReference")
    result["site_statuses"] = []
    for site_status in root.findall(
        "energy:energyInfrastructureSiteStatus", NAMESPACES
    ):
        parsed_site = {
            "id": site_status.get("id"),
            "version": site_status.get("version"),
            "last_updated": _text(
                site_status, "facilities:lastUpdated"
            ),
            "station_statuses": [],
        }
        for station_status in site_status.findall(
            "energy:energyInfrastructureStationStatus", NAMESPACES
        ):
            parsed_station = {
                "id": station_status.get("id"),
                "version": station_status.get("version"),
                "is_available": _text(
                    station_status, "energy:isAvailable"
                ),
                "refill_point_statuses": [],
            }
            for status in station_status.findall(
                "energy:refillPointStatus", NAMESPACES
            ):
                parsed_station["refill_point_statuses"].append({
                    "id": status.get("id"),
                    "connector_index": status.get("connectorIndex"),
                    "status": _text(status, "energy:status"),
                })
            parsed_site["station_statuses"].append(parsed_station)
        result["site_statuses"].append(parsed_site)
    return result
