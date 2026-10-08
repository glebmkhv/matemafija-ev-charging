import sqlite3
import unittest
from datetime import datetime, timezone

from src.spatial_redistribution import (
    DisplacedStartProxy, ReceivingCapacity, SpatialRedistributionSpecification,
    SpatialSite, load_spatial_sites, redistribute_displaced_start_proxies,
)


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def sites():
    return (
        SpatialSite("A", 54.6872, 25.2797),
        SpatialSite("B", 54.6917, 25.2797),
        SpatialSite("C", 54.7052, 25.2797),
    )


class SpatialRedistributionTest(unittest.TestCase):
    def test_nearest_capacity_is_used_without_overbooking(self):
        result = redistribute_displaced_start_proxies(
            sites(),
            (DisplacedStartProxy("A", NOW, 3),),
            (
                ReceivingCapacity("B", NOW, 2),
                ReceivingCapacity("C", NOW, 5),
            ),
            SpatialRedistributionSpecification(1_000, 1),
            random_seed=7,
        )
        self.assertEqual(result.total_allocated_start_proxy_count, 2)
        self.assertEqual(result.total_unassigned_count, 1)
        self.assertEqual(result.destination_zero_availability_created_count, 1)
        self.assertEqual(result.allocations[0].destination_site_id, "B")
        destination = next(
            item for item in result.destination_outcomes
            if item.destination_site_id == "B"
        )
        self.assertEqual(destination.projected_available_after_redistribution, 0)

    def test_zero_participation_preserves_all_as_unassigned(self):
        result = redistribute_displaced_start_proxies(
            sites(), (DisplacedStartProxy("A", NOW, 3),),
            (ReceivingCapacity("B", NOW, 3),),
            SpatialRedistributionSpecification(1_000, 0), random_seed=1,
        )
        self.assertEqual(result.total_candidate_count, 0)
        self.assertEqual(result.total_allocated_start_proxy_count, 0)
        self.assertEqual(result.total_unassigned_count, 3)

    def test_receiver_fraction_reserves_capacity(self):
        result = redistribute_displaced_start_proxies(
            sites(), (DisplacedStartProxy("A", NOW, 4),),
            (ReceivingCapacity("B", NOW, 3),),
            SpatialRedistributionSpecification(
                1_000, 1, receiver_capacity_fraction=.5,
            ), random_seed=1,
        )
        self.assertEqual(result.total_allocated_start_proxy_count, 1)
        self.assertEqual(result.destination_outcomes[0].usable_receiving_capacity, 1)

    def test_competing_origins_share_one_global_capacity_bound(self):
        result = redistribute_displaced_start_proxies(
            sites(),
            (
                DisplacedStartProxy("A", NOW, 2),
                DisplacedStartProxy("C", NOW, 2),
            ),
            (ReceivingCapacity("B", NOW, 2),),
            SpatialRedistributionSpecification(2_000, 1), random_seed=2,
        )
        self.assertEqual(result.total_allocated_start_proxy_count, 2)
        self.assertEqual(result.total_unassigned_count, 2)

    def test_loads_only_current_sites_with_coordinates(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("""CREATE TABLE ocpi_locations (
            ocpi_location_key TEXT, latitude REAL, longitude REAL, is_current INTEGER
        )""")
        connection.executemany(
            "INSERT INTO ocpi_locations VALUES (?, ?, ?, ?)",
            (("A", 54.68, 25.28, 1), ("B", None, None, 1),
             ("C", 54.70, 25.30, 0)),
        )
        self.assertEqual([item.site_id for item in load_spatial_sites(connection)], ["A"])


if __name__ == "__main__":
    unittest.main()
