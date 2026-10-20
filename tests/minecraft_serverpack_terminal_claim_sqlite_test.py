#!/usr/bin/env python3
"""Exercise the Controller's terminal claim SQL with real SQLite transactions.

This isolates database concurrency semantics; it is not a full repository E2E test.
"""
import sqlite3
import ast
import tempfile
import threading
import unittest
from pathlib import Path


CLAIM_SQL = (
    "UPDATE agent_instance_provisioning SET updated_at=updated_at "
    "WHERE provisioning_id=? AND status NOT IN ('completed','failed')"
)


class TerminalClaimSQLiteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "claim.sqlite")
        with sqlite3.connect(self.db) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE agent_instance_provisioning "
                "(provisioning_id TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at INTEGER)"
            )
            db.execute("CREATE TABLE published (id INTEGER PRIMARY KEY, provisioning_id TEXT)")
            db.execute(
                "INSERT INTO agent_instance_provisioning VALUES ('p1','running',0)"
            )

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self):
        return sqlite3.connect(self.db, timeout=5, isolation_level=None)

    def test_claim_sql_matches_both_controller_repositories(self):
        root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "database/agent_instance_provisioning_repository.py",
            "dashboard/agent_instance_provisioning_repository.py",
        ):
            with self.subTest(repository=relative_path):
                source = (root / relative_path).read_text(encoding="utf-8")
                tree = ast.parse(source)
                repository = next(
                    node for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == "AgentInstanceProvisioningRepository"
                )
                apply_result = next(
                    node for node in repository.body
                    if isinstance(node, ast.FunctionDef) and node.name == "apply_result"
                )
                body = ast.get_source_segment(source, apply_result)
                self.assertIn("UPDATE agent_instance_provisioning SET ", body)
                self.assertIn("updated_at=updated_at", body)
                self.assertIn("WHERE provisioning_id={ph} AND status NOT IN ('completed','failed')", body)

    def test_replay_claim_does_not_republish(self):
        for _ in range(2):
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                claimed = db.execute(CLAIM_SQL, ("p1",)).rowcount
                if claimed:
                    db.execute("INSERT INTO published(provisioning_id) VALUES ('p1')")
                    db.execute(
                        "UPDATE agent_instance_provisioning SET status='completed' WHERE provisioning_id='p1'"
                    )
                db.commit()
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM published").fetchone()[0], 1)

    def test_failed_publication_rolls_back_claim_and_state(self):
        with self.assertRaisesRegex(RuntimeError, "publish failed"):
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.assertEqual(db.execute(CLAIM_SQL, ("p1",)).rowcount, 1)
                db.execute("INSERT INTO published(provisioning_id) VALUES ('p1')")
                db.execute(
                    "UPDATE agent_instance_provisioning SET status='completed' WHERE provisioning_id='p1'"
                )
                raise RuntimeError("publish failed")
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM agent_instance_provisioning").fetchone()[0], "running")
            self.assertEqual(db.execute("SELECT count(*) FROM published").fetchone()[0], 0)

    def test_two_concurrent_claims_publish_once(self):
        barrier = threading.Barrier(2)
        errors = []
        claims = []
        def worker():
            try:
                db = self.connect()
                try:
                    barrier.wait(timeout=5)
                    db.execute("BEGIN IMMEDIATE")
                    claimed = db.execute(CLAIM_SQL, ("p1",)).rowcount
                    claims.append(claimed)
                    if claimed:
                        db.execute("INSERT INTO published(provisioning_id) VALUES ('p1')")
                        db.execute(
                            "UPDATE agent_instance_provisioning SET status='completed' WHERE provisioning_id='p1'"
                        )
                    db.commit()
                finally:
                    db.close()
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(errors, errors)
        self.assertEqual(sorted(claims), [0, 1])
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM published").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
