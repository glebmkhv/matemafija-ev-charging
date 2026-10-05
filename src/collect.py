"""Collect near-real-time OCPI snapshots and save them to SQLite."""

import argparse
from pathlib import Path
import subprocess
import sys
import time

from database import DATABASE_PATH, save_ocpi_snapshot
from ocpi import fetch_locations, fetch_tariffs


DEFAULT_INTERVAL_SECONDS = 5 * 60
TARIFF_INTERVAL_SECONDS = 24 * 60 * 60


def collect_once(include_tariffs=True):
    """Download and persist one complete OCPI snapshot."""
    locations = fetch_locations()
    tariffs = None

    if include_tariffs:
        try:
            tariffs = fetch_tariffs()
        except Exception as error:
            print(f"Tariff collection failed: {error}")

    result = save_ocpi_snapshot(locations, tariffs=tariffs)

    print(
        "Saved snapshot "
        f"{result['collector_run_id']}: "
        f"{result['locations']} locations, "
        f"{result['evses']} EVSEs, "
        f"{result['connectors']} connectors, "
        f"{result['history_rows']} observations, "
        f"{result['tariffs']} tariffs."
    )
    print(f"Database: {DATABASE_PATH}")
    return tariffs is not None


def run_monitor(interval_seconds=DEFAULT_INTERVAL_SECONDS):
    """Collect snapshots repeatedly until the user presses Ctrl+C."""
    print("OCPI monitor started. Press Ctrl+C to stop.")

    last_tariff_collection = None

    try:
        while True:
            try:
                now = time.monotonic()
                include_tariffs = (
                    last_tariff_collection is None
                    or now - last_tariff_collection >= TARIFF_INTERVAL_SECONDS
                )
                tariffs_collected = collect_once(
                    include_tariffs=include_tariffs
                )
                if include_tariffs and tariffs_collected:
                    last_tariff_collection = time.monotonic()
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
