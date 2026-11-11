from __future__ import annotations
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/"core",ROOT/"database",ROOT/"tests"):
    if str(path) not in sys.path:sys.path.insert(0,str(path))
from minecraft_serverpack_pending_publication_atomic_test import AtomicPendingPublicationTest
from minecraft_serverpack_content_receipt import confirmed_serverpack_receipt,ServerPackControllerReceiptError


class ServerPackReceiptTests(unittest.TestCase):
    def setUp(self):
        self.fixture=AtomicPendingPublicationTest(
            methodName="test_completed_agent_result_publishes_bundle_in_same_completion_transaction")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.pending=self.fixture.pending()
        self.repo,self.operation=self.fixture.enqueue(self.pending)
        self.kwargs={
            "backend":self.fixture.backend,
            "provisioning_id":self.operation["provisioning_id"],
            "agent_id":"pr839-isolated-agent",
            "instance_id":"pr855-controller-atomic",
            "candidate_sha256":self.pending["candidate_sha256"],
        }

    def test_rejects_before_commit(self):
        with self.assertRaisesRegex(ServerPackControllerReceiptError,"not completed"):
            confirmed_serverpack_receipt(**self.kwargs)

    def complete(self):
        return self.repo.apply_result("pr839-isolated-agent",
            self.fixture.completed(self.operation,self.pending))

    def test_verifies_published_revision_and_replay(self):
        self.complete()
        a=confirmed_serverpack_receipt(**self.kwargs)
        b=confirmed_serverpack_receipt(**self.kwargs)
        self.assertEqual(a,b)
        self.assertEqual(a["status"],"verified")
        self.assertEqual(a["bundle_revision"],2)
        self.assertEqual(a["child_count"],1)

    def test_rejects_wrong_candidate(self):
        self.complete()
        self.kwargs["candidate_sha256"]="f"*64
        with self.assertRaisesRegex(ServerPackControllerReceiptError,"candidate receipt mismatch"):
            confirmed_serverpack_receipt(**self.kwargs)

    def test_rejects_other_agent(self):
        self.complete()
        self.kwargs["agent_id"]="wrong-agent"
        with self.assertRaisesRegex(ServerPackControllerReceiptError,"does not belong"):
            confirmed_serverpack_receipt(**self.kwargs)

    def test_rejects_changed_loader(self):
        self.complete()
        with self.fixture.backend.transaction() as c:
            c.execute("UPDATE instances SET build_id=? WHERE id=?",("26.1.2.999","pr855-controller-atomic"))
        with self.assertRaisesRegex(ServerPackControllerReceiptError,"runtime identity diverged"):
            confirmed_serverpack_receipt(**self.kwargs)

    def test_rejects_changed_manifest(self):
        self.complete()
        with self.fixture.backend.transaction() as c:
            c.execute("UPDATE content_bundles SET manifest_sha256=? WHERE instance_id=?",("e"*64,"pr855-controller-atomic"))
        with self.assertRaisesRegex(ServerPackControllerReceiptError,"stale or changed"):
            confirmed_serverpack_receipt(**self.kwargs)

    def test_rejects_mutated_revision_manifest_artifact(self):
        self.complete()
        with self.fixture.backend.transaction() as c:
            row=c.execute("SELECT bundle_id,revision,manifest_json FROM content_bundle_revisions ORDER BY revision DESC LIMIT 1").fetchone()
            data=__import__("json").loads(row["manifest_json"])
            data["members"][0]["artifact"]["sha256"]="f"*64
            c.execute("UPDATE content_bundle_revisions SET manifest_json=? WHERE bundle_id=? AND revision=?",
                      (__import__("json").dumps(data),row["bundle_id"],row["revision"]))
        with self.assertRaisesRegex(ServerPackControllerReceiptError,"member artifact changed"):
            confirmed_serverpack_receipt(**self.kwargs)

    def test_rejects_pending_child(self):
        self.complete()
        with self.fixture.backend.transaction() as c:
            c.execute("UPDATE content_assignments SET desired_state=? WHERE instance_id=? AND content_id=?",
                      ("absent","pr855-controller-atomic","mod-a"))
        with self.assertRaisesRegex(ServerPackControllerReceiptError,"installed assignments"):
            confirmed_serverpack_receipt(**self.kwargs)


if __name__=="__main__":unittest.main()
