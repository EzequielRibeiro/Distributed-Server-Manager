#!/usr/bin/env python3
from __future__ import annotations
import json,os,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];MATRIX=ROOT/"catalog"/"v2"/"support-matrix.json"
JAVA_IDS={"minecraft.java.arclight","minecraft.java.fabric","minecraft.java.folia","minecraft.java.forge","minecraft.java.neoforge","minecraft.java.paper","minecraft.java.purpur","minecraft.java.quilt","minecraft.java.spongevanilla","minecraft.java.vanilla","minecraft.java.youer"}
def supported_profiles(runtime_root:Path)->set[str]:
 env=os.environ.copy();env["PYTHONPATH"]=str(runtime_root);cp=subprocess.run([sys.executable,"-c","from profiles.registry import supported_profiles; print('\\n'.join(supported_profiles()))"],cwd=ROOT,env=env,capture_output=True,text=True,check=False)
 if cp.returncode:raise AssertionError(cp.stderr)
 return {line.strip().lower() for line in cp.stdout.splitlines() if line.strip()}
class CatalogAgentRuntimeProfileParityTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.matrix=json.loads(MATRIX.read_text(encoding="utf-8"));cls.linux=supported_profiles(ROOT/"agents"/"linux"/"runtime");cls.windows=supported_profiles(ROOT/"agents"/"windows"/"runtime")
 def test_every_published_os_runtime_has_local_profile(self):
  failures=[]
  for item in self.matrix.get("published_runtimes",[]):
   runtime_id=str(item.get("id") or "").lower()
   for platform in item.get("os",[]):
    profiles=self.linux if platform=="linux" else self.windows if platform=="windows" else set()
    if runtime_id not in profiles:failures.append(f"{runtime_id}:{platform}")
  self.assertEqual(failures,[],"published runtimes without Agent profile: "+", ".join(failures))
 def test_windows_claims_only_materialized_runtime_families(self):
  self.assertIn("dayz.stable",self.windows);self.assertTrue(JAVA_IDS.issubset(self.windows));self.assertIn("mindustry.github",self.windows);self.assertIn("arma3.stable",self.windows)
  for runtime_id in ("rust.stable","minecraft.bedrock.vanilla","arksurvivalascended.stable"):
   self.assertNotIn(runtime_id,self.windows)
 def test_deferred_runtime_is_not_published(self):
  published={str(item.get("id") or "").lower() for item in self.matrix.get("published_runtimes",[])};deferred={str(item.get("id") or "").lower() for item in self.matrix.get("deferred_runtimes",[])}
  self.assertFalse(published & deferred);self.assertFalse(JAVA_IDS & deferred);self.assertTrue(JAVA_IDS.issubset(published))
  for runtime_id in ("mindustry.github","arma3.stable"):
   self.assertIn(runtime_id,published);self.assertNotIn(runtime_id,deferred)
if __name__=="__main__":unittest.main()
