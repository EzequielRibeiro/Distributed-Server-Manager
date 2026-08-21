import unittest

from database.federation import (
    FederationController,
    FederationRoute,
    build_inventory_snapshot,
    select_controller,
    validate_inventory_snapshot,
)


class FederationContractTests(unittest.TestCase):
    def test_controller_requires_https(self):
        with self.assertRaises(ValueError):
            FederationController("dc-a", "http://dc-a.example", datacenter_id="dc-a").validate()

    def test_snapshot_is_bounded_and_verifiable(self):
        snapshot = build_inventory_snapshot(
            controller_id="controller-sp",
            sequence=7,
            agents=[{"agent_id": "a1", "datacenter_id": "sp1", "status": "active", "token": "secret"}],
            instances=[{"instance_id": "i1", "agent_id": "a1", "game_id": "dayz", "customer_id": "c1", "password": "secret"}],
        )
        payload = validate_inventory_snapshot(snapshot, "controller-sp")
        self.assertEqual(payload["sequence"], 7)
        self.assertNotIn("token", payload["agents"][0])
        self.assertNotIn("password", payload["instances"][0])

    def test_snapshot_identity_mismatch_fails_closed(self):
        snapshot = build_inventory_snapshot(controller_id="controller-sp", sequence=1)
        with self.assertRaises(ValueError):
            validate_inventory_snapshot(snapshot, "controller-rj")

    def test_route_prefers_datacenter_then_priority(self):
        controllers = [
            FederationController("sp-a", "https://sp-a.example", "br-se", "sp", status="online", priority=20),
            FederationController("sp-b", "https://sp-b.example", "br-se", "sp", status="online", priority=10),
        ]
        routes = [
            FederationRoute("datacenter", "sp", "sp-a", priority=5),
            FederationRoute("datacenter", "sp", "sp-b", priority=10),
        ]
        selected = select_controller(controllers, routes, region_id="br-se", datacenter_id="sp")
        self.assertEqual(selected.controller_id, "sp-a")

    def test_offline_controller_is_never_selected(self):
        controllers = [FederationController("sp-a", "https://sp-a.example", "br-se", "sp", status="offline")]
        routes = [FederationRoute("datacenter", "sp", "sp-a")]
        self.assertIsNone(select_controller(controllers, routes, datacenter_id="sp"))


if __name__ == "__main__":
    unittest.main()
