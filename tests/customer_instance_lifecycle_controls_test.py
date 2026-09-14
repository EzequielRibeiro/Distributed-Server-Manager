#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LIVE = ROOT / "dashboard" / "web" / "customer-instance-runtime-live.js"


class CustomerInstanceLifecycleControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = RUNTIME_LIVE.read_text(encoding="utf-8")

    def test_all_lifecycle_actions_share_one_pending_gate(self):
        self.assertIn('lifecycleActions=["start","restart","stop"]', self.source)
        self.assertIn('lifecyclePending=""', self.source)
        self.assertIn('pending=!!lifecyclePending', self.source)
        self.assertIn('button.disabled=true', self.source)

    def test_lifecycle_fetch_is_detected_before_request_is_sent(self):
        self.assertIn('/^\\/api\\/instance\\/(start|restart|stop)$/', self.source)
        self.assertIn('setLifecyclePending(action);applyControls();', self.source)
        self.assertIn('return await nativeFetch(input,options)', self.source)

    def test_authoritative_overview_is_refreshed_before_unlock(self):
        self.assertIn('await refreshOverview()', self.source)
        self.assertIn('setLifecyclePending("");applyControls()', self.source)

    def test_repeated_or_contradictory_clicks_are_blocked_in_capture_phase(self):
        self.assertIn('if(lifecyclePending){event.preventDefault();event.stopImmediatePropagation();return}', self.source)
        self.assertIn('addEventListener("click",event=>rejectInvalidLifecycleClick(action,event),true)', self.source)

    def test_runtime_state_prefers_authoritative_workspace_projection(self):
        self.assertIn('overview?.runtime?.state||overview?.instance?.status', self.source)
        self.assertIn('syncRuntimeState();applyControls()', self.source)

    def test_unknown_runtime_state_fails_closed_for_lifecycle_actions(self):
        self.assertIn('startable=stopped||state==="failed"', self.source)
        self.assertIn('pr||!startable||busy', self.source)
        self.assertIn('pr||!running||busy', self.source)
        self.assertIn('action==="start"&&!startable', self.source)

    def test_pending_action_has_visible_progress_label(self):
        self.assertIn('start:"Iniciando…"', self.source)
        self.assertIn('restart:"Reiniciando…"', self.source)
        self.assertIn('stop:"Parando…"', self.source)


if __name__ == "__main__":
    unittest.main()
