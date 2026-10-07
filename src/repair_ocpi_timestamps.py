"""Audit or repair OCPI timestamps that omit an explicit UTC offset."""

import argparse

from database_v2 import (
    DATABASE_PATH,
    _ocpi_utc_text,
    _quality_for_ocpi_timestamp,
    connect_database,
)


CURRENT_TABLES = (
    "ocpi_locations",
    "ocpi_evses",
    "ocpi_connectors",
    "ocpi_tariffs",
)


def _is_timezone_naive(value):
    if not value:
        return False
    return not value.endswith("Z") and "+" not in value[10:] and "-" not in value[10:]


def audit(connection):
    result = {}
    for table in CURRENT_TABLES:
        rows = connection.execute(
            f"SELECT source_last_updated_raw FROM {table} "
            "WHERE source_last_updated_raw IS NOT NULL"
        )
        values = [row[0] for row in rows]
        result[table] = {
            "total": len(values),
            "timezone_naive": sum(_is_timezone_naive(value) for value in values),
        }
    result["ocpi_evse_status_observations"] = dict(
        connection.execute(
            """SELECT COUNT(*) AS total,
                      SUM(source_timestamp_quality LIKE 'future%') AS future
               FROM ocpi_evse_status_observations"""
        ).fetchone()
    )
    return result


def repair(connection):
    connection.create_function("ocpi_utc", 1, _ocpi_utc_text)
    connection.create_function(
        "ocpi_age",
        2,
        lambda source, observed: _quality_for_ocpi_timestamp(source, observed)[0],
    )
    connection.create_function(
        "ocpi_quality",
        2,
        lambda source, observed: _quality_for_ocpi_timestamp(source, observed)[1],
    )

    with connection:
        for table in CURRENT_TABLES:
            connection.execute(
                f"""UPDATE {table}
                    SET source_last_updated_utc=ocpi_utc(source_last_updated_raw)
                    WHERE source_last_updated_raw IS NOT NULL"""
            )
        connection.execute(
            """UPDATE source_entity_revisions
               SET source_last_updated_utc=ocpi_utc(source_last_updated_raw)
               WHERE source_last_updated_raw IS NOT NULL
                 AND data_source_id=(
                     SELECT data_source_id FROM data_sources
                     WHERE source_code='VIA_LIETUVA_OCPI'
                 )"""
        )
        connection.execute(
            """UPDATE ocpi_evse_status_observations
               SET source_last_updated_utc=ocpi_utc(source_last_updated_raw),
                   source_timestamp_age_seconds=ocpi_age(
                       source_last_updated_raw, observed_at
                   ),
                   source_timestamp_quality=ocpi_quality(
                       source_last_updated_raw, observed_at
                   )
               WHERE source_last_updated_raw IS NOT NULL"""
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="update the database")
    parser.add_argument("--database", default=str(DATABASE_PATH))
    arguments = parser.parse_args()

    connection = connect_database(arguments.database)
    try:
        print("Before:", audit(connection))
        if arguments.apply:
            repair(connection)
            print("After:", audit(connection))
        else:
            print("Audit only. Re-run with --apply to repair stored UTC values.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
