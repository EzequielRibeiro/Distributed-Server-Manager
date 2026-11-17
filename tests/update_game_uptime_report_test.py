"""Game uptime report: no external systemd calls or production mutation."""
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader,module_from_spec
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
loader=SourceFileLoader("uptime_report",str(ROOT/"update-manager/game-uptime-report.py"))
spec=spec_from_loader(loader.name,loader)
report_module=module_from_spec(spec)
loader.exec_module(report_module)


class UptimeReportTests(unittest.TestCase):
    def test_active_mixed_instances_are_never_authorized(self):
        def inspect(unit):
            if "minecraft" in unit:
                raise report_module.guard.GateError("replaceable console supervisor")
            return {"main_pid":12345}
        result=report_module.report(
            list_units=lambda:["capivara-instance-minecraft-005.service",
                               "capivara-instance-dayz-001.service"],inspect=inspect)
        self.assertFalse(result["live_no_drain_authorized"])
        self.assertEqual(result["managed_active_units"],2)
        self.assertEqual(sum(int(x["identity_verified"]) for x in result["units"]),1)
        self.assertTrue(all(not x["eligible"] for x in result["units"]))

    def test_failed_inventory_fails_closed(self):
        def failure():
            raise report_module.guard.GateError("systemd unavailable")
        result=report_module.report(list_units=failure)
        self.assertFalse(result["live_no_drain_authorized"])
        self.assertIn("inventory_error",result)

    def test_invalid_units_fail_closed(self):
        result=report_module.report(list_units=lambda:["dsm-dashboard.service"])
        self.assertIn("inventory_error",result)

    def test_zero_active_units_not_authorization(self):
        result=report_module.report(list_units=lambda:[])
        self.assertEqual(result["managed_active_units"],0)
        self.assertFalse(result["live_no_drain_authorized"])


if __name__=="__main__":unittest.main()
