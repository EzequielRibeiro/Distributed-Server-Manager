#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"

sys.path.insert(0, str(DATABASE))

from backend import DatabaseConfig
from backend_factory import create_backend
from location_repository import LocationRepository


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE controllers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    controller_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (controller_id)
        REFERENCES controllers(id)
);

CREATE TABLE regions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT,
    continent_code TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL
);

CREATE TABLE datacenters (
    id TEXT PRIMARY KEY,
    region_id TEXT NOT NULL,
    name TEXT NOT NULL,
    provider TEXT,
    city TEXT,
    country_code TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL,
    FOREIGN KEY (region_id)
        REFERENCES regions(id)
);

CREATE TABLE agent_locations (
    agent_id TEXT PRIMARY KEY,
    datacenter_id TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    public_host TEXT,
    status TEXT NOT NULL,
    FOREIGN KEY (agent_id)
        REFERENCES agents(id),
    FOREIGN KEY (datacenter_id)
        REFERENCES datacenters(id)
);

CREATE TABLE instances (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    FOREIGN KEY (agent_id)
        REFERENCES agents(id)
);
"""


class LocationRepositoryTest(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temp.name) / "capivara.db"
        )

        connection = sqlite3.connect(
            self.database_path
        )

        connection.executescript(SCHEMA)

        connection.execute(
            """
            INSERT INTO controllers(
                id,
                name,
                status
            )
            VALUES (?, ?, ?)
            """,
            (
                "controller-a",
                "Controller A",
                "active",
            ),
        )

        connection.executemany(
            """
            INSERT INTO agents(
                id,
                controller_id,
                node_id,
                name,
                status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "agent-a",
                    "controller-a",
                    "node-a",
                    "Agent A",
                    "active",
                ),
                (
                    "agent-b",
                    "controller-a",
                    "node-b",
                    "Agent B",
                    "active",
                ),
            ],
        )

        connection.commit()
        connection.close()

        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(
                    self.database_path
                ),
            )
        )

        self.repository = LocationRepository(
            self.backend
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_upsert_region_creates_and_updates(self):
        self.repository.upsert_region(
            region_id="br-se",
            name="Brasil Sudeste",
            country_code="BR",
            continent_code="SA",
            latitude=-23.5,
            longitude=-46.6,
        )

        regions = self.repository.regions()

        self.assertEqual(
            len(regions),
            1,
        )
        self.assertEqual(
            regions[0]["id"],
            "br-se",
        )
        self.assertEqual(
            regions[0]["name"],
            "Brasil Sudeste",
        )

        self.repository.upsert_region(
            region_id="br-se",
            name="Sudeste do Brasil",
            country_code="BR",
            continent_code="SA",
            latitude=-23.55,
            longitude=-46.63,
        )

        regions = self.repository.regions()

        self.assertEqual(
            len(regions),
            1,
        )
        self.assertEqual(
            regions[0]["name"],
            "Sudeste do Brasil",
        )
        self.assertAlmostEqual(
            regions[0]["latitude"],
            -23.55,
        )

    def test_upsert_datacenter_creates_and_updates(self):
        self.repository.upsert_region(
            region_id="br-se",
            name="Brasil Sudeste",
        )

        self.repository.upsert_datacenter(
            datacenter_id="dc-sp",
            region_id="br-se",
            name="Sao Paulo 1",
            provider="local",
            city="Sao Paulo",
            country_code="BR",
            latitude=-23.5,
            longitude=-46.6,
        )

        datacenters = (
            self.repository.datacenters(
                "br-se"
            )
        )

        self.assertEqual(
            len(datacenters),
            1,
        )
        self.assertEqual(
            datacenters[0]["id"],
            "dc-sp",
        )

        self.repository.upsert_datacenter(
            datacenter_id="dc-sp",
            region_id="br-se",
            name="Sao Paulo Principal",
            provider="capivara",
            city="Sao Paulo",
            country_code="BR",
            latitude=-23.55,
            longitude=-46.63,
        )

        datacenters = (
            self.repository.datacenters(
                "br-se"
            )
        )

        self.assertEqual(
            len(datacenters),
            1,
        )
        self.assertEqual(
            datacenters[0]["name"],
            "Sao Paulo Principal",
        )
        self.assertEqual(
            datacenters[0]["provider"],
            "capivara",
        )

    def test_upsert_agent_location_creates_and_updates(self):
        self.repository.upsert_region(
            region_id="br-se",
            name="Brasil Sudeste",
        )

        self.repository.upsert_datacenter(
            datacenter_id="dc-sp",
            region_id="br-se",
            name="Sao Paulo",
        )

        self.repository.upsert_agent_location(
            agent_id="agent-a",
            datacenter_id="dc-sp",
            public_host="agent-a.example",
        )

        candidates = (
            self.repository.candidates(
                "controller-a"
            )
        )

        self.assertEqual(
            len(candidates),
            1,
        )
        self.assertEqual(
            candidates[0]["agent_id"],
            "agent-a",
        )
        self.assertEqual(
            candidates[0]["region_id"],
            "br-se",
        )
        self.assertEqual(
            candidates[0]["datacenter_id"],
            "dc-sp",
        )
        self.assertEqual(
            candidates[0]["public_host"],
            "agent-a.example",
        )

        self.repository.upsert_agent_location(
            agent_id="agent-a",
            datacenter_id="dc-sp",
            latitude=-22.0,
            longitude=-47.0,
            public_host="new.example",
        )

        candidates = (
            self.repository.candidates(
                "controller-a"
            )
        )

        self.assertEqual(
            len(candidates),
            1,
        )
        self.assertEqual(
            candidates[0]["public_host"],
            "new.example",
        )
        self.assertAlmostEqual(
            candidates[0]["latitude"],
            -22.0,
        )

    def test_candidate_instance_count_is_correct(self):
        self.repository.upsert_region(
            region_id="br-se",
            name="Brasil Sudeste",
        )

        self.repository.upsert_datacenter(
            datacenter_id="dc-sp",
            region_id="br-se",
            name="Sao Paulo",
        )

        self.repository.upsert_agent_location(
            agent_id="agent-a",
            datacenter_id="dc-sp",
        )

        connection = sqlite3.connect(
            self.database_path
        )

        connection.executemany(
            """
            INSERT INTO instances(
                id,
                agent_id
            )
            VALUES (?, ?)
            """,
            [
                ("instance-1", "agent-a"),
                ("instance-2", "agent-a"),
            ],
        )

        connection.commit()
        connection.close()

        candidates = (
            self.repository.candidates(
                "controller-a"
            )
        )

        self.assertEqual(
            candidates[0]["instance_count"],
            2,
        )

    def test_candidate_can_be_filtered_by_region(self):
        self.repository.upsert_region(
            region_id="br-se",
            name="Brasil Sudeste",
        )

        self.repository.upsert_region(
            region_id="us-east",
            name="US East",
            country_code="US",
        )

        self.repository.upsert_datacenter(
            datacenter_id="dc-sp",
            region_id="br-se",
            name="Sao Paulo",
        )

        self.repository.upsert_datacenter(
            datacenter_id="dc-us",
            region_id="us-east",
            name="Virginia",
        )

        self.repository.upsert_agent_location(
            agent_id="agent-a",
            datacenter_id="dc-sp",
        )

        self.repository.upsert_agent_location(
            agent_id="agent-b",
            datacenter_id="dc-us",
        )

        candidates = (
            self.repository.candidates(
                "controller-a",
                region_id="br-se",
            )
        )

        self.assertEqual(
            len(candidates),
            1,
        )
        self.assertEqual(
            candidates[0]["agent_id"],
            "agent-a",
        )

    def test_invalid_datacenter_region_is_rejected(self):
        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            self.repository.upsert_datacenter(
                datacenter_id="dc-invalid",
                region_id="missing-region",
                name="Invalid",
            )

    def test_invalid_agent_location_is_rejected(self):
        self.repository.upsert_region(
            region_id="br-se",
            name="Brasil Sudeste",
        )

        self.repository.upsert_datacenter(
            datacenter_id="dc-sp",
            region_id="br-se",
            name="Sao Paulo",
        )

        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            self.repository.upsert_agent_location(
                agent_id="missing-agent",
                datacenter_id="dc-sp",
            )


if __name__ == "__main__":
    unittest.main()
