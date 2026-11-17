#!/usr/bin/env python3
"""Verify the DayZ-only Customer tab uses the authenticated instance game."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CustomerDayzGameGateTest(unittest.TestCase):
    def test_main_overview_configures_game_specific_tab(self):
        main = (ROOT / "dashboard/web/customer-instance-v2.js").read_text(encoding="utf-8")
        dayz = (ROOT / "dashboard/web/customer-dayz.js").read_text(encoding="utf-8")
        self.assertIn("window.CapivaraInstanceDayz?.configure?.(overview)", main)
        self.assertIn('String(instance.id||"")!==iid', dayz)
        self.assertIn('toLowerCase()!=="dayz"', dayz)

    @unittest.skipUnless(shutil.which("node"), "Node.js not installed")
    def test_tab_visibility_and_api_are_game_gated(self):
        case = ROOT / "tests/customer_dayz_game_gate.test.js"
        result = subprocess.run(["node", str(case)], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout+"\n"+result.stderr)
        self.assertIn("PASS:", result.stdout)

class DayzMapRuntimeReconciliationContractTest(unittest.TestCase):
    def test_active_map_can_be_reapplied_after_unrestarted_completion(self):
        script = (ROOT / "dashboard/web/customer-dayz.js").read_text(encoding="utf-8")
        self.assertIn('latestChangeResult.changed===false&&latestChangeResult.restarted===false&&!latestChangeResult.reconciled', script)
        self.assertIn('reconcile?"Reaplicar mapa e reiniciar":"Aplicar mapa e reiniciar"', script)
        self.assertIn('(!!m.active&&!reconcile)', script)

class DayzWipeScheduleFieldsContractTest(unittest.TestCase):
    def test_wipe_uses_mobile_safe_date_and_time_selects(self):
        script = (ROOT / "dashboard/web/customer-dayz.js").read_text(encoding="utf-8")
        self.assertIn('wipeDateWrap=el("div","","date-select")', script)
        self.assertIn('wipeDateWrap.id="dayz-wipe-date"', script)
        self.assertIn('wipeTime=el("div","","time-select")', script)
        self.assertIn('wipeTime.id="dayz-wipe-time"', script)
        self.assertIn('wipeDay.append(new Option("Dia","")', script)
        self.assertIn('wipeMonth.append(new Option("Mês","")', script)
        self.assertIn('wipeYear.append(new Option("Ano","")', script)
        self.assertNotIn('type="datetime-local"', script)
        self.assertNotIn('type="date"', script)
        self.assertNotIn('type="time"', script)
        self.assertNotIn('showPicker', script)
        self.assertIn('if(hasDate&&!completeDate){toast("Selecione dia, mês e ano do wipe.");return}', script)
        self.assertIn('`${wipeYear.value}-${wipeMonth.value}-${wipeDay.value}`', script)
        self.assertIn('`${wipeHour.value}:${wipeMinute.value}`', script)
        self.assertIn('scheduled_at:future?future.toISOString():null', script)
        self.assertIn('const pendingWipe=operations.find(op=>op.action==="wipe"', script)
        self.assertIn('op.status==="delivered"||(op.status==="queued"&&(!op.scheduled_at||new Date(op.scheduled_at)<=new Date()))', script)
        self.assertIn('wipeDay.value=String(due.getDate()).padStart(2,"0")', script)
        self.assertIn('let wipeFormDirty=false', script)
        self.assertIn('const markWipeDirty=()=>{wipeFormDirty=true}', script)
        self.assertIn('[wipeDay,wipeMonth,wipeYear,wipeHour,wipeMinute].forEach', script)
        self.assertIn('&&!wipeFormDirty&&!editing)load()', script)
        self.assertNotIn('nativePickerActive', script)

if __name__=="__main__":
    unittest.main()
