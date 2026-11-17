"""Read-only integration tests for the expired upload backlog audit."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "database"))
from artifact_transfer_repository import ArtifactTransferRepository

IDS = ("transfer-" + "1" * 32, "transfer-" + "2" * 32, "transfer-" + "3" * 32)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class AuditSession:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if not sql.lstrip().upper().startswith("SELECT"):
            raise AssertionError("audit must not mutate the database")
        if "FROM artifact_transfers" in sql:
            return Result([
                {"transfer_id": IDS[0], "status": "expired", "size_bytes": 100},
                {"transfer_id": IDS[1], "status": "expired", "size_bytes": 200},
                {"transfer_id": IDS[2], "status": "expired", "size_bytes": 300},
            ])
        if "FROM content_assignments " in sql:
            return Result([{"exists": 1}] if IDS[0] in params[0] else [])
        if "FROM content_assignment_revisions " in sql:
            return Result([{"exists": 1}] if IDS[1] in params[0] else [])
        raise AssertionError(f"unexpected SQL: {sql}")


class CleanupAuditTests(unittest.TestCase):
    def test_separates_current_historical_and_unreferenced(self):
        session = AuditSession()
        repo = ArtifactTransferRepository.__new__(ArtifactTransferRepository)
        repo.dialect = SimpleNamespace(placeholder="?")

        @contextmanager
        def database_session():
            yield session

        repo.session = database_session
        result = repo.audit_expired_content_uploads()

        self.assertEqual(result["scanned"], 3)
        self.assertEqual(result["current_reference"], 1)
        self.assertEqual(result["historical_reference"], 1)
        self.assertEqual(result["unreferenced_expired"], 1)
        self.assertEqual(result["unreferenced_bytes"], 300)
        self.assertEqual(result["protected_bytes"], 300)
        self.assertEqual(result["not_expired"], 0)

    def test_audit_does_not_delete_or_enqueue(self):
        session = AuditSession()
        repo = ArtifactTransferRepository.__new__(ArtifactTransferRepository)
        repo.dialect = SimpleNamespace(placeholder="%s")

        @contextmanager
        def database_session():
            yield session

        repo.session = database_session
        repo.audit_expired_content_uploads()
        self.assertTrue(session.statements)
        self.assertTrue(all(s.lstrip().upper().startswith("SELECT") for s in session.statements))


if __name__ == "__main__":
    unittest.main()
