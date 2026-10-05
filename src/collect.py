"""Collect near-real-time OCPI snapshots and save them to SQLite."""

import argparse
import time

from database import DATABASE_PATH, save_ocpi_snapshot
from ocpi import fetch_locations


DEFAULT_INTERVAL_SECONDS = 5 * 60


def collect_once():
    """Download and persist one complete OCPI snapshot."""
    locations = fetch_locations()
    result = save_ocpi_snapshot(locations)

    print(
        "Saved snapshot "
        f"{result['collector_run_id']}: "
        f"{result['locations']} locations, "
        f"{result['evses']} EVSEs, "
        f"{result['history_rows']} history rows."
    )
    print(f"Database: {DATABASE_PATH}")


def run_monitor(interval_seconds=DEFAULT_INTERVAL_SECONDS):
    """Collect snapshots repeatedly until the user presses Ctrl+C."""
    print("OCPI monitor started. Press Ctrl+C to stop.")

    try:
        while True:
            try:
                collect_once()
            except Exception as error:
                print(f"Collection failed: {error}")

            print(f"Next collection starts in {interval_seconds} seconds.")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nOCPI monitor stopped by user.")


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
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()

    if arguments.once:
        collect_once()
    else:
        run_monitor(arguments.interval)
