#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"dashboard"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"database"))
from minecraft_recovery_event_persistence import persist_recovery_claims
CLAIM={"instance_id":"mc005","agent_id":"agent1","status":"recovered","recovered_at":"2026-10-23T23:28:00Z","observed_at":"2026-10-23T23:29:00Z","filesystem_status":"recovered","original_loader_version":"26.1.2.94"}
class PersistenceTest(unittest.TestCase):
    def test_idempotent_event_id(self):
        records=[]
        class Events:
            def __init__(self,backend):pass
            def publish(self,event):
                records.append(event)
                return {"created":True}
        with patch("minecraft_recovery_event_persistence.UniversalEventRepository",Events):
            stats=persist_recovery_claims(object(),[CLAIM,CLAIM])
        self.assertEqual(stats,{"accepted":1,"created":1})
        self.assertEqual(records[0]["event_type"],"MINECRAFT_SERVERPACK_MIGRATION_RECOVERED")
        self.assertEqual(records[0]["instance_id"],"mc005")
    def test_repeated_heartbeat_does_not_create_second_event(self):
        event_ids = set()
        class Events:
            def __init__(self, backend):
                pass
            def publish(self, event):
                created = event["event_id"] not in event_ids
                event_ids.add(event["event_id"])
                return {"created": created}
        with patch("minecraft_recovery_event_persistence.UniversalEventRepository", Events):
            first = persist_recovery_claims(object(), [CLAIM])
            second = persist_recovery_claims(object(), [CLAIM])
        self.assertEqual(first, {"accepted": 1, "created": 1})
        self.assertEqual(second, {"accepted": 1, "created": 0})
        self.assertEqual(len(event_ids), 1)

    def test_invalid_claim_is_not_stored(self):
        with patch("minecraft_recovery_event_persistence.UniversalEventRepository") as repo:
            self.assertEqual(persist_recovery_claims(object(),[{**CLAIM,"status":"failed"}]),{"accepted":0,"created":0})
            repo.return_value.publish.assert_not_called()
if __name__=="__main__":unittest.main()
