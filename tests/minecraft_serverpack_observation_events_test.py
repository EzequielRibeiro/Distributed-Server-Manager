"""Bounded, owned and time-expiring filesystem-only Server Pack observations."""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'dashboard'),str(ROOT/'database')]
from minecraft_serverpack_observation_events import (
    persist_serverpack_runtime_observations,classify_recent_serverpack_observation,
)

class ObservationEventsTest(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.stamp=self.now.isoformat().replace('+00:00','Z')
        self.item={'instance_id':'inst','content_id':'pack','bundle_revision':2,
                   'status':'physical_runtime_verified','reason':'boot_not_observed',
                   'boot_verified':False,'ready_for_release':False}

    def test_owned_event_is_deduplicated_and_never_healthy(self):
        with patch('minecraft_serverpack_observation_events.UniversalEventRepository') as mocked:
            repo=mocked.return_value
            repo._instance_owned_by.return_value=True
            repo.publish.return_value={'created':True}
            result=persist_serverpack_runtime_observations(object(),agent_id='a',
                    observations=[self.item,self.item],observed_at=self.stamp)
        self.assertEqual(result,{'accepted':1,'created':1})
        saved=repo.publish.call_args.args[0]
        self.assertEqual(saved['data']['proof_scope'],'current_filesystem_only')
        self.assertIs(saved['data']['boot_verified'],False)
        self.assertIs(saved['data']['release_authorized'],False)
        event={'event_type':saved['event_type'],'agent_id':'a',
               'instance_id':'inst','occurred_at':saved['occurred_at'],
               'source':saved['source'],'source_id':saved['source_id'],
               'data':saved['data']}
        self.assertEqual(classify_recent_serverpack_observation(event,agent_id='a',
            instance_id='inst',content_id='pack',bundle_revision=2,now=self.now),'verified')
        self.assertEqual(classify_recent_serverpack_observation(event,agent_id='a',
            instance_id='inst',content_id='pack',bundle_revision=3,now=self.now),'missing')
        self.assertEqual(classify_recent_serverpack_observation(
            {**event,'source':'agent.runtime'},agent_id='a',
            instance_id='inst',content_id='pack',bundle_revision=2,now=self.now),'missing')
        self.assertEqual(classify_recent_serverpack_observation(event,agent_id='other',
            instance_id='inst',content_id='pack',bundle_revision=2,now=self.now),'missing')
        self.assertEqual(classify_recent_serverpack_observation(event,agent_id='a',
            instance_id='inst',content_id='pack',bundle_revision=2,
            now=self.now+timedelta(hours=3)),'stale')

    def test_reject_unowned_future_and_invalid_health_claim(self):
        with patch('minecraft_serverpack_observation_events.UniversalEventRepository') as mocked:
            repo=mocked.return_value
            repo._instance_owned_by.return_value=False
            self.assertEqual(persist_serverpack_runtime_observations(object(),agent_id='a',
                observations=[self.item],observed_at=self.stamp)['accepted'],0)
            repo.publish.assert_not_called()
            self.assertEqual(persist_serverpack_runtime_observations(object(),agent_id='a',
                observations=[self.item],observed_at=(self.now+timedelta(hours=2)).isoformat())['accepted'],0)
            self.assertEqual(persist_serverpack_runtime_observations(object(),agent_id='a',
                observations=[{**self.item,'boot_verified':True}],observed_at=self.stamp)['accepted'],0)

if __name__=='__main__':unittest.main()