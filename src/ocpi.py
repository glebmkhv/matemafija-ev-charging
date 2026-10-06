"""Download current locations and EVSE statuses from public OCPI."""

import requests


LOCATIONS_URL = "https://ev.vialietuva.lt/ocpi/2.3.0/locations"
TARIFFS_URL = "https://ev.vialietuva.lt/ocpi/2.3.0/tariffs"
CREDENTIALS_URL = "https://ev.vialietuva.lt/ocpi/2.3.0/credentials"
PAGE_SIZE = 1000


def fetch_locations():
    """Download all OCPI location pages using explicit pagination."""
    locations = []
    offset = 0
    total_count = None

    with requests.Session() as session:
        while total_count is None or offset < total_count:
            print(f"Downloading OCPI page with offset {offset}...")

            response = session.get(
                LOCATIONS_URL,
                params={
                    "offset": offset,
                    "limit": PAGE_SIZE,
                },
                timeout=(10, 60),
            )
            response.raise_for_status()

            payload = response.json()

            if payload.get("status_code") != 1000:
                message = payload.get(
                    "status_message",
                    "Unknown OCPI error",
                )
                raise ValueError(f"OCPI request failed: {message}")

            page_locations = payload.get("data")

            if not isinstance(page_locations, list):
                raise ValueError("Expected OCPI 'data' to contain a list.")

            locations.extend(page_locations)

            print(
                f"Received {len(page_locations)} locations; "
                f"collected {len(locations)} so far."
            )

            if total_count is None:
                total_header = response.headers.get("X-Total-Count")

                if total_header is not None:
                    total_count = int(total_header)
                    print(f"Server reports {total_count} total records.")

            if not page_locations:
                break

            offset += PAGE_SIZE

    return locations


def fetch_tariffs():
    """Download the public OCPI tariff list."""
    print("Downloading OCPI tariffs...")

    response = requests.get(TARIFFS_URL, timeout=(10, 60))
    response.raise_for_status()
    payload = response.json()

    if payload.get("status_code") != 1000:
        message = payload.get(
            "status_message",
            "Unknown OCPI error",
        )
        raise ValueError(f"OCPI tariff request failed: {message}")

    tariffs = payload.get("data")
    if not isinstance(tariffs, list):
        raise ValueError("Expected OCPI tariff 'data' to contain a list.")

    print(f"Received {len(tariffs)} tariffs.")
    return tariffs


def fetch_credentials_metadata():
    """Download public OCPI credentials metadata; callers must discard tokens."""
    print("Downloading OCPI credentials metadata...")
    response = requests.get(CREDENTIALS_URL, timeout=(10, 60))
    response.raise_for_status()
    payload = response.json()
    if payload.get("status_code") != 1000:
        message = payload.get("status_message", "Unknown OCPI error")
        raise ValueError(f"OCPI credentials request failed: {message}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Expected OCPI credentials 'data' to contain an object.")
    return data


def print_summary(locations):
    """Print basic counts and one example from Vilnius."""
    vilnius_locations = [
        location
        for location in locations
        if (location.get("city") or "").strip().casefold() == "vilnius"
    ]

    evse_count = sum(
        len(location.get("evses") or [])
        for location in locations
    )

    print(f"Locations downloaded: {len(locations)}")
    print(f"EVSEs downloaded: {evse_count}")
    print(f"Vilnius locations: {len(vilnius_locations)}")

    if not vilnius_locations:
        return

    example = vilnius_locations[0]

    print("\nExample location:")
    print(f"ID: {example.get('id')}")
    print(f"Name: {example.get('name')}")
    print(f"Address: {example.get('address')}")

    for evse in example.get("evses") or []:
        print(
            f"EVSE: {evse.get('evse_id')} | "
            f"Status: {evse.get('status')} | "
            f"Source updated: {evse.get('last_updated')}"
        )


if __name__ == "__main__":
    locations = fetch_locations()
    print_summary(locations)
