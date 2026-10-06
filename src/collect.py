"""Collect near-real-time OCPI and DATEX II snapshots into database v2."""

import argparse
from pathlib import Path
import subprocess
import sys
import time

from database_v2 import (
    DATABASE_PATH,
    save_datex_dynamic_publication,
    save_datex_static_publication,
    save_ocpi_credentials_metadata,
    save_ocpi_locations_snapshot,
    save_ocpi_tariffs_snapshot,
)
from database import save_ocpi_snapshot as save_legacy_ocpi_snapshot
from datex import (
    fetch_dynamic_publication,
    fetch_static_publication,
    parse_dynamic_publication,
    parse_static_publication,
)
from ocpi import fetch_credentials_metadata, fetch_locations, fetch_tariffs


DEFAULT_INTERVAL_SECONDS = 5 * 60
TARIFF_INTERVAL_SECONDS = 24 * 60 * 60
DATEX_STATIC_INTERVAL_SECONDS = 24 * 60 * 60
CREDENTIALS_INTERVAL_SECONDS = 24 * 60 * 60


def collect_ocpi_once(include_tariffs=True):
    """Download and persist complete OCPI locations and optional tariffs."""
    locations = fetch_locations()
    location_result = save_ocpi_locations_snapshot(locations)
    tariff_result = None
    tariffs = None

    if include_tariffs:
        try:
            tariffs = fetch_tariffs()
            tariff_result = save_ocpi_tariffs_snapshot(tariffs)
        except Exception as error:
            print(f"Tariff collection failed: {error}")

    # Keep the existing dashboard operational until its planned v2 migration.
    save_legacy_ocpi_snapshot(locations, tariffs=tariffs)

    print(
        "Saved OCPI locations snapshot "
        f"{location_result['collection_run_id']}: "
        f"{location_result['locations']} locations, "
        f"{location_result['evses']} EVSEs, "
        f"{location_result['connectors']} connectors."
    )
    if tariff_result:
        print(
            "Saved OCPI tariffs snapshot "
            f"{tariff_result['collection_run_id']}: "
            f"{tariff_result['tariffs']} tariffs."
        )
    return tariff_result is not None


def collect_datex_dynamic_once():
    """Download and persist one DATEX II dynamic status publication."""
    response = fetch_dynamic_publication()
    parsed = parse_dynamic_publication(response["payload_bytes"])
    result = save_datex_dynamic_publication(
        parsed,
        response["payload_bytes"],
        http_status=response["http_status"],
    )
    print(
        "Saved DATEX dynamic publication "
        f"{result['collection_run_id']}: {result['stations']} stations, "
        f"{result['statuses']} statuses, "
        f"{result['unmatched_stations']} stations without current static data."
    )


def collect_datex_static_once():
    """Download and persist one DATEX II static publication."""
    response = fetch_static_publication()
    parsed = parse_static_publication(response["payload_bytes"])
    result = save_datex_static_publication(
        parsed,
        response["payload_bytes"],
        http_status=response["http_status"],
    )
    print(
        "Saved DATEX static publication "
        f"{result['collection_run_id']}: {result['stations']} stations, "
        f"{result['refill_points']} refill points, "
        f"{result['connectors']} connectors."
    )


def collect_once(
    include_tariffs=True,
    include_datex_static=True,
    include_credentials=True,
):
    """Collect every enabled source once; failures remain source-specific."""
    results = {
        "tariffs_collected": False,
        "datex_static_collected": False,
        "credentials_collected": False,
    }
    try:
        results["tariffs_collected"] = collect_ocpi_once(
            include_tariffs=include_tariffs
        )
    except Exception as error:
        print(f"OCPI locations collection failed: {error}")
    try:
        collect_datex_dynamic_once()
    except Exception as error:
        print(f"DATEX dynamic collection failed: {error}")
    if include_datex_static:
        try:
            collect_datex_static_once()
            results["datex_static_collected"] = True
        except Exception as error:
            print(f"DATEX static collection failed: {error}")
    if include_credentials:
        try:
            credentials = fetch_credentials_metadata()
            result = save_ocpi_credentials_metadata(credentials)
            print(
                "Saved OCPI credentials metadata "
                f"{result['collection_run_id']}: {result['roles']} roles; "
                "authentication tokens were not stored."
            )
            results["credentials_collected"] = True
        except Exception as error:
            print(f"OCPI credentials metadata collection failed: {error}")
    print(f"Database: {DATABASE_PATH}")
    return results


def run_monitor(interval_seconds=DEFAULT_INTERVAL_SECONDS):
    """Collect snapshots repeatedly until the user presses Ctrl+C."""
    print("OCPI and DATEX II monitor started. Press Ctrl+C to stop.")

    last_tariff_collection = None
    last_datex_static_collection = None
    last_credentials_collection = None

    try:
        while True:
            try:
                now = time.monotonic()
                include_tariffs = (
                    last_tariff_collection is None
                    or now - last_tariff_collection >= TARIFF_INTERVAL_SECONDS
                )
                include_datex_static = (
                    last_datex_static_collection is None
                    or now - last_datex_static_collection
                    >= DATEX_STATIC_INTERVAL_SECONDS
                )
                include_credentials = (
                    last_credentials_collection is None
                    or now - last_credentials_collection
                    >= CREDENTIALS_INTERVAL_SECONDS
                )
                results = collect_once(
                    include_tariffs=include_tariffs,
                    include_datex_static=include_datex_static,
                    include_credentials=include_credentials,
                )
                if include_tariffs and results["tariffs_collected"]:
                    last_tariff_collection = time.monotonic()
                if include_datex_static and results["datex_static_collected"]:
                    last_datex_static_collection = time.monotonic()
                if include_credentials and results["credentials_collected"]:
                    last_credentials_collection = time.monotonic()
            except Exception as error:
                print(f"Collection failed: {error}")

            print(f"Next collection starts in {interval_seconds} seconds.")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nOCPI monitor stopped by user.")


def run_with_dashboard(interval_seconds=DEFAULT_INTERVAL_SECONDS):
    """Run the collector and a local Streamlit dashboard together."""
    dashboard_path = Path(__file__).with_name("dashboard.py")
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(dashboard_path),
        "--server.port=8501",
        "--browser.gatherUsageStats=false",
    ]
    dashboard_process = subprocess.Popen(command)

    try:
        run_monitor(interval_seconds)
    finally:
        if dashboard_process.poll() is None:
            dashboard_process.terminate()
            dashboard_process.wait(timeout=10)


def parse_arguments():
    """Read optional command-line settings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="collect one snapshot and exit",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="seconds to wait between completed collection cycles",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="run the collector with the local real-time dashboard",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()

    if arguments.once and arguments.dashboard:
        raise SystemExit("Choose either --once or --dashboard, not both.")
    if arguments.once:
        collect_once()
    elif arguments.dashboard:
        run_with_dashboard(arguments.interval)
    else:
        run_monitor(arguments.interval)
