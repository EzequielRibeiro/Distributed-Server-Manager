#!/usr/bin/env python3
"""Provider/game-neutral YARA-X gate for Universal Content."""
from __future__ import annotations
import json,os,shutil,stat,subprocess
from pathlib import Path
from typing import Any
try:
 from security_yarax import managed_binary as _managed_yarax_binary, status as _managed_engine_status
except ModuleNotFoundError:
 _managed_yarax_binary=lambda:None
 _managed_engine_status=lambda:{}
try:
 from security_yarax_rules import managed_rules_path as _managed_yarax_rules_path, status as _managed_rules_status
except ModuleNotFoundError:
 _managed_yarax_rules_path=lambda:None
 _managed_rules_status=lambda:{}

STATE_ROOT=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",Path(os.environ.get("PROGRAMDATA",r"C:\\ProgramData"))/"CapivaraAgent"/"state"))
LEGACY_RULES_PATH=Path(os.environ.get("PROGRAMDATA",r"C:\\ProgramData"))/"CapivaraAgent"/"security"/"yara-rules"
try:SCAN_TIMEOUT=max(5,min(int(os.environ.get("CAPIVARA_YARAX_TIMEOUT_SECONDS","120")),900))
except (TypeError,ValueError):SCAN_TIMEOUT=120
_BLOCK_TAGS={"block","blocked","malware","critical","deny"}

class ContentSecurityError(RuntimeError):pass
class ContentSecurityRejected(ContentSecurityError):
 def __init__(self,verdict:dict[str,Any]):self.verdict=verdict;super().__init__(str(verdict.get("reason") or verdict.get("security_state") or "content security rejected"))

def _binary()->str|None:
 configured=str(os.environ.get("CAPIVARA_YARAX_BIN") or "").strip()
 if configured:
  path=Path(configured)
  return str(path) if path.is_file() else None
 managed=_managed_yarax_binary()
 if managed:return managed
 managed_status=_managed_engine_status()
 if str(managed_status.get("state") or "")=="error":return None
 return shutil.which("yr")

def _rules_path()->Path:
 configured=str(os.environ.get("CAPIVARA_YARAX_RULES_PATH") or "").strip()
 if configured:return Path(configured)
 managed=_managed_yarax_rules_path()
 if managed:return Path(managed)
 managed_status=_managed_rules_status()
 if str(managed_status.get("state") or "")=="error":
  return STATE_ROOT/"security"/"yara-x"/"rulesets"/".invalid-managed-ruleset"
 return LEGACY_RULES_PATH

def _rule_files(path:Path|None=None)->list[Path]:
 path=path or _rules_path()
 if path.is_symlink():return []
 if path.is_file():return [path] if path.suffix.lower() in {".yar",".yara"} else []
 if not path.is_dir():return []
 return sorted(p for p in path.rglob("*") if p.is_file() and not p.is_symlink() and p.suffix.lower() in {".yar",".yara"})[:10000]

def scanner_status()->dict[str,Any]:
 engine_override=str(os.environ.get("CAPIVARA_YARAX_BIN") or "").strip()
 rules_override=str(os.environ.get("CAPIVARA_YARAX_RULES_PATH") or "").strip()
 engine_candidate_status=_managed_engine_status() if not engine_override else {}
 rules_candidate_status=_managed_rules_status() if not rules_override else {}
 managed_binary=_managed_yarax_binary() if not engine_override else None
 managed_rules=_managed_yarax_rules_path() if not rules_override else None
 binary=_binary();rules_path=_rules_path();rules=_rule_files(rules_path);ready=bool(binary and rules)
 engine_managed=bool(not engine_override and (managed_binary or str(engine_candidate_status.get("state") or "")=="error"))
 rules_managed=bool(not rules_override and (managed_rules or str(rules_candidate_status.get("state") or "")=="error"))
 engine_status=engine_candidate_status if engine_managed else {}
 rules_status=rules_candidate_status if rules_managed else {}
 engine_state=str(engine_status.get("state") or ("ready" if binary else "missing"))
 rules_state=str(rules_status.get("state") or ("ready" if rules else "missing"))
 state="ready" if ready else "missing_rules" if binary else "missing_engine"
 if engine_state=="error":state="engine_error"
 elif rules_state=="error":state="rules_error"
 last_error=None
 if engine_state=="error":last_error=str(engine_status.get("error") or "YARA-X engine validation failed")[:1000]
 elif rules_state=="error":last_error=str(rules_status.get("error") or "YARA-X ruleset validation failed")[:1000]
 elif not binary:last_error="YARA-X engine is unavailable"
 elif not rules:last_error="YARA-X rules are unavailable"
 return {
  "engine":"yara-x","enforced":True,"ready":ready,"state":state,
  "engine_state":engine_state,"engine_version":engine_status.get("installed_version") or engine_status.get("observed_version"),
  "engine_pinned_version":engine_status.get("pinned_version"),"engine_path":str(binary) if binary else None,
  "engine_managed":engine_managed,"engine_error":engine_status.get("error"),
  "rules_state":rules_state,"rules_count":len(rules),"rules_path":str(rules_path),
  "ruleset_version":rules_status.get("ruleset_version"),"ruleset_pinned_version":rules_status.get("pinned_ruleset_version"),
  "ruleset_sha256":rules_status.get("sha256"),"ruleset_expected_sha256":rules_status.get("expected_sha256"),
  "ruleset_checksum_valid":rules_status.get("checksum_valid"),"rules_managed":rules_managed,"last_error":last_error,
 }

def _verdict(state:str,*,reason:str|None=None,matches:list[dict[str,Any]]|None=None)->dict[str,Any]:
 return {"security_state":state,"engine":"yara-x","policy_version":1,"reason":reason,"matches":list(matches or [])[:200]}

def _validate_target_tree(target:Path)->str|None:
 if target.is_symlink():return "content scan target is a symbolic link"
 if target.is_file():return None
 if not target.is_dir():return "content scan target is not a regular file or directory"
 count=0;total=0
 for current,dirs,files in os.walk(target,followlinks=False):
  current_path=Path(current)
  for name in dirs:
   candidate=current_path/name
   if candidate.is_symlink():return "content scan tree contains a symbolic link"
  for name in files:
   candidate=current_path/name
   try:mode=candidate.lstat().st_mode
   except OSError:return "content scan tree cannot be inspected"
   if not stat.S_ISREG(mode):return "content scan tree contains a non-regular file"
   count+=1;total+=candidate.stat().st_size
   if count>100000 or total>128*1024*1024*1024:return "content scan tree exceeds safety limits"
 return None

def scan_content(path:Path|str)->dict[str,Any]:
 original=Path(path)
 if original.is_symlink():return _verdict("blocked",reason="content scan target is a symbolic link")
 target=original.resolve();binary=_binary();rules_path=_rules_path();rules=_rule_files(rules_path)
 if not target.exists():return _verdict("scan_failed",reason="content scan target is unavailable")
 unsafe=_validate_target_tree(target)
 if unsafe:return _verdict("blocked",reason=unsafe)
 if not binary:return _verdict("scan_failed",reason="YARA-X engine is unavailable")
 if not rules:return _verdict("scan_failed",reason="YARA-X rules are unavailable")
 args=[binary,"scan","--output-format=ndjson","-m","-g","--timeout",str(SCAN_TIMEOUT)]
 if target.is_dir():args.append("--recursive")
 args.extend((str(rules_path),str(target)))
 try:
  completed=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=SCAN_TIMEOUT+5,check=False)
 except (OSError,subprocess.TimeoutExpired) as exc:return _verdict("scan_failed",reason=f"YARA-X scan failed: {exc}")
 if completed.returncode!=0:return _verdict("scan_failed",reason=(completed.stderr or completed.stdout or f"YARA-X exited with {completed.returncode}")[-1000:])
 matches=[];blocked=False
 for line in (completed.stdout or "").splitlines():
  if not line.strip():continue
  try:item=json.loads(line)
  except json.JSONDecodeError:return _verdict("scan_failed",reason="YARA-X returned invalid NDJSON")
  if not isinstance(item,dict):continue
  for rule in item.get("rules") or []:
   if not isinstance(rule,dict):continue
   tags=[str(v).strip().lower() for v in rule.get("tags") or [] if str(v).strip()]
   blocked=blocked or bool(_BLOCK_TAGS.intersection(tags));matches.append({"rule":str(rule.get("identifier") or "unknown")[:191],"tags":tags[:20]})
 if matches:return _verdict("blocked" if blocked else "suspicious",reason="YARA-X matched content",matches=matches)
 return _verdict("clean")

def require_clean(path:Path|str)->dict[str,Any]:
 result=scan_content(path)
 if result["security_state"]!="clean":raise ContentSecurityRejected(result)
 return result

__all__=["ContentSecurityError","ContentSecurityRejected","require_clean","scan_content","scanner_status"]
