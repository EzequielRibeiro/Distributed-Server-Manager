#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/"dashboard"/"web"/"customer-instance-v2.js"


class M8CustomerContentUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=UI.read_text(encoding="utf-8")

    def test_installed_content_actions_are_server_authoritative(self):
        text=self.text
        self.assertIn('allowed=item.actions&&typeof item.actions==="object"?item.actions:{}',text)
        for action in ("enable","disable","reorder","update","rollback","remove"):
            self.assertIn(f"allowed.{action}",text)

    def test_browser_does_not_reconstruct_installed_action_capabilities(self):
        text=self.text
        self.assertNotIn('if(can("content.install")){const toggle=',text)
        self.assertNotIn('if(item.update?.supported&&item.desired_state!=="absent")',text)
        self.assertNotIn('if(item.update?.rollback_available)',text)
        self.assertNotIn('if(item.content_type!=="modpack")',text)
        self.assertNotIn('if(can("content.remove")){const remove=',text)

    def test_missing_action_projection_fails_closed(self):
        text=self.text
        self.assertIn('allowed=item.actions&&typeof item.actions==="object"?item.actions:{}',text)
        self.assertNotIn('allowed=item.actions||',text)


    def test_content_mutation_errors_are_visible_to_customer(self):
        text=self.text
        self.assertIn('catch(error){toast(error.message||"Não foi possível concluir a operação de conteúdo.");return false}',text)

    def test_search_result_install_always_reports_progress_or_failure(self):
        text=self.text
        self.assertIn('button.onclick=()=>installDiscoveredContent(item,button,feedback)',text)
        self.assertIn('button.textContent="Verificando…"',text)
        self.assertIn('feedback.textContent="Não foi possível solicitar a instalação: "+',text)
        self.assertIn('button.disabled=accepted',text)

    def test_ui_bootstrap_cache_version_updated(self):
        html=(ROOT/"dashboard"/"web"/"customer-instance.html").read_text(encoding="utf-8")
        self.assertIn("/customer-instance-v2.js?v=24",html)

    def test_content_status_has_sse_push_and_resilient_fallback(self):
        text=self.text
        self.assertIn("new EventSource",text)
        self.assertIn("/content/stream?instance_id=",text)
        self.assertIn('addEventListener("content-state"',text)
        self.assertIn("scheduleContentFallback(15000)",text)
        self.assertIn('&_ts=${Date.now()}',text)
        self.assertIn('{cache:"no-store"}',text)
        self.assertIn('document.addEventListener("visibilitychange"',text)

    def test_security_notice_is_presented_without_rule_internals(self):
        text=self.text
        self.assertIn('securityNotice=item.security_notice&&typeof item.security_notice==="object"?item.security_notice:null',text)
        self.assertIn('Segurança: ${String(securityNotice.message).slice(0,500)}',text)


    def test_search_result_icons_use_same_origin_proxy(self):
        text=self.text
        self.assertIn('function contentIconUrl(url)',text)
        self.assertIn('/content/icon?',text)
        self.assertIn('icon.src=contentIconUrl(item.icon_url)',text)
        self.assertNotIn('icon.src=item.icon_url',text)


if __name__=="__main__":
    unittest.main()
