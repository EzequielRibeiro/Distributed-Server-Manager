"""Move large artifacts over the Windows Agent outbound Controller connection."""
from __future__ import annotations
import hashlib,http.client,json,os,ssl
from pathlib import Path
from urllib.parse import urlencode,urlparse
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));STATE=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"));RESULT=STATE/"artifact-results";BACKUPS=Path(os.environ.get("CAPIVARA_BACKUP_ROOT",STATE/"backups")).resolve()
def _safe(v):
 s=str(v or "").strip()
 if not s or len(s)>191 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in s):raise ValueError("invalid artifact token")
 return s
def _write(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(tmp,path)
def _headers(config):return {"X-Capivara-Agent-Credential":str(config["credential_id"]),"X-Capivara-Agent-Secret":str(config["credential_secret"]),"X-Capivara-Agent-Fingerprint":str(config["fingerprint"])}
def _connection(config):
 u=urlparse(str(config["controller_url"]));host=u.hostname
 if not host:raise ValueError("invalid controller_url")
 if u.scheme=="https":return http.client.HTTPSConnection(host,u.port or 443,timeout=60,context=ssl.create_default_context()),u
 if u.scheme=="http":return http.client.HTTPConnection(host,u.port or 80,timeout=60),u
 raise ValueError("unsupported controller scheme")
def _backup_artifact(instance_id,backup_id):
 directory=(BACKUPS/_safe(instance_id)).resolve();directory.relative_to(BACKUPS);matches=[p for p in directory.glob(f"{_safe(backup_id)}.tar*") if p.is_file() and not p.is_symlink()]
 if len(matches)!=1:raise FileNotFoundError("backup artifact not found")
 return matches[0]
def _put(config,transfer_id,path):
 conn,u=_connection(config);size=path.stat().st_size;endpoint=(u.path.rstrip("/")+"/api/agent/artifacts/upload?"+urlencode({"transfer_id":transfer_id})) or "/api/agent/artifacts/upload";headers={**_headers(config),"Content-Type":"application/octet-stream","Content-Length":str(size)}
 conn.putrequest("PUT",endpoint)
 for k,v in headers.items():conn.putheader(k,v)
 conn.endheaders();sent=0
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):conn.send(chunk);sent+=len(chunk)
 response=conn.getresponse();body=response.read();conn.close()
 if response.status not in {200,201}:raise RuntimeError(f"Controller artifact upload failed ({response.status}): {body[:500]!r}")
 return sent
def _get(config,transfer_id,destination,expected_size=None,expected_sha=None):
 conn,u=_connection(config);endpoint=(u.path.rstrip("/")+"/api/agent/artifacts/download?"+urlencode({"transfer_id":transfer_id})) or "/api/agent/artifacts/download";conn.request("GET",endpoint,headers=_headers(config));response=conn.getresponse()
 if response.status!=200:
  body=response.read();conn.close();raise RuntimeError(f"Controller artifact download failed ({response.status}): {body[:500]!r}")
 destination.parent.mkdir(parents=True,exist_ok=True);tmp=destination.with_suffix(destination.suffix+".part");h=hashlib.sha256();total=0
 try:
  with tmp.open("wb") as out:
   while True:
    chunk=response.read(1024*1024)
    if not chunk:break
    total+=len(chunk);h.update(chunk);out.write(chunk)
  conn.close()
  if expected_size is not None and total!=int(expected_size):raise ValueError("artifact size mismatch")
  if expected_sha and h.hexdigest()!=str(expected_sha):raise ValueError("artifact checksum mismatch")
  os.replace(tmp,destination)
 finally:
  try:tmp.unlink()
  except FileNotFoundError:pass
 return total
def handle_command(config,command):
 tid=_safe(command.get("transfer_id"));path=RESULT/f"{tid}.json"
 try:old=json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
 except Exception:old=None
 if isinstance(old,dict) and old.get("status") in {"completed","failed"}:return old
 try:
  direction=str(command.get("direction") or "");purpose=str(command.get("purpose") or "");iid=_safe(command.get("instance_id"));source=str(command.get("source_ref") or "");destination=str(command.get("destination_ref") or "")
  if direction=="agent_to_controller" and purpose in {"backup_export","deleted_backup_export"}:transferred=_put(config,tid,_backup_artifact(iid,source))
  elif direction=="controller_to_agent" and purpose in {"backup_import","backup_clone"}:
   backup_id=_safe(destination or source or tid);suffix=".tar.gz" if str(command.get("filename") or "").endswith(".gz") else ".tar";dest=(BACKUPS/iid/f"{backup_id}{suffix}").resolve();dest.relative_to(BACKUPS);transferred=_get(config,tid,dest,command.get("size_bytes"),command.get("sha256"))
  else:raise ValueError("unsupported artifact transfer purpose")
  result={"transfer_id":tid,"instance_id":iid,"status":"completed","transferred_bytes":transferred}
 except Exception as exc:result={"transfer_id":tid,"instance_id":command.get("instance_id"),"status":"failed","error":str(exc)[:2000]}
 _write(path,result);return result
def read_result():
 for p in sorted(RESULT.glob("*.json")) if RESULT.exists() else []:
  try:v=json.loads(p.read_text(encoding="utf-8"))
  except Exception:continue
  if isinstance(v,dict):return v
 return None
def clear_result(transfer_id):
 try:(RESULT/f"{_safe(transfer_id)}.json").unlink()
 except FileNotFoundError:pass
__all__=["clear_result","handle_command","read_result"]
