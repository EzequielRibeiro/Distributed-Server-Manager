#!/usr/bin/env python3
"""Customer Workspace HTTP surface for Universal Content."""
from __future__ import annotations
import hashlib
import json
import time
from urllib.parse import parse_qs,urlparse
from urllib.request import HTTPRedirectHandler,Request,build_opener
from controller_session import session_user_from_headers
from content_action_capabilities import project_content_actions
from customer_content_workspace import CustomerContentWorkspaceService
from customer_content_upload_service import CustomerContentUploadService
from instance_activity_repository import InstanceActivityRepository
from json_serialization import to_json_compatible
from server_update_api import instance_update_policy_view,set_instance_update_policy
from server_update_repository import ServerUpdateRepository

PATH="/api/customer/instance/workspace/content"
SEARCH=PATH+"/search"
ICON=PATH+"/icon"
BUNDLE=PATH+"/bundle"
UPLOAD=PATH+"/upload"
UPLOAD_URL=UPLOAD+"/url"
UPLOAD_STATUS=UPLOAD+"/status"
UPLOAD_FINALIZE=UPLOAD+"/finalize"
UPLOAD_CANCEL=UPLOAD+"/cancel"
UPDATE_POLICY=PATH+"/update-policy"
UPDATE_POLICY_ITEM=UPDATE_POLICY+"/item"
STREAM=PATH+"/stream"


ICON_HOST_SUFFIXES=(".modrinth.com",".forgecdn.net")
ICON_MAX_BYTES=4*1024*1024

def _allowed_icon_url(value):
 parsed=urlparse(str(value or "").strip())
 if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:return False
 host=parsed.hostname.lower().rstrip(".")
 return any(host.endswith(suffix) and host!=suffix.lstrip(".") or host==suffix.lstrip(".") for suffix in ICON_HOST_SUFFIXES)

class _IconRedirectHandler(HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  if not _allowed_icon_url(newurl):raise ValueError("content icon redirect is not allowed")
  return super().redirect_request(req,fp,code,msg,headers,newurl)

def _fetch_content_icon(url):
 if not _allowed_icon_url(url):raise ValueError("content icon source is not allowed")
 request=Request(url,headers={"Accept":"image/avif,image/webp,image/png,image/jpeg,image/gif;q=0.8","User-Agent":"Capivara-DSM/2"})
 opener=build_opener(_IconRedirectHandler())
 with opener.open(request,timeout=10) as response:
  content_type=str(response.headers.get_content_type() or "").lower()
  if content_type not in {"image/avif","image/webp","image/png","image/jpeg","image/gif"}:raise ValueError("content icon response is not a supported image")
  length=response.headers.get("Content-Length")
  if length and int(length)>ICON_MAX_BYTES:raise ValueError("content icon exceeds size limit")
  data=response.read(ICON_MAX_BYTES+1)
  if len(data)>ICON_MAX_BYTES:raise ValueError("content icon exceeds size limit")
  return content_type,data

def install_customer_content_http(legacy,authenticate):
 previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST;previous_put=getattr(legacy.DashboardHandler,"do_PUT",None)
 def backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
 def send(self,status,payload):return self.send_json(status,to_json_compatible(payload))
 def user_for(self,area=None):
  explicit=str(area or self.headers.get("X-Capivara-Auth-Area") or "").strip().lower()
  if explicit in {"customer","controller"}:
   value=session_user_from_headers(self.headers,area=explicit)
   if value is not None:return value
  else:
   value=session_user_from_headers(self.headers)
   if value is not None:return value
  try:return authenticate(self.headers)
  except Exception:return None
 def require_user(self,area=None):
  user=user_for(self,area=area)
  if user is None:self.unauthorized();return None
  if str(user.get("role") or "").lower() not in {"customer","admin","controller"}:self.forbidden();return None
  return user
 def iid(parsed,body=None):return str((body or {}).get("instance_id") or (parse_qs(parsed.query,keep_blank_values=True).get("instance_id") or [""])[0] or "").strip()
 def one(parsed,name,default=""):return (parse_qs(parsed.query,keep_blank_values=True).get(name) or [default])[0]
 def content_length(self):
  value=str(self.headers.get("Content-Length") or "").strip()
  if not value:raise ValueError("Content-Length is required")
  length=int(value)
  if length<0 or length>64*1024*1024*1024:raise ValueError("content upload exceeds 64 GiB transfer limit")
  return length
 def transfer_view(item):return {k:item.get(k) for k in ("transfer_id","instance_id","direction","purpose","filename","status","size_bytes","transferred_bytes","sha256","last_error","expires_at")}
 def content_view(user,instance_id):
  api=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT);items=api.list(user,instance_id)
  return {"content":project_content_actions(api,user,instance_id,items)}
 def sse_frame(event,payload,event_id=None):
  data=json.dumps(to_json_compatible(payload),ensure_ascii=False,separators=(",",":"))
  lines=[]
  if event_id:lines.append(f"id: {event_id}")
  lines.append(f"event: {event}")
  lines.extend(f"data: {line}" for line in data.splitlines() or [""])
  return ("\n".join(lines)+"\n\n").encode("utf-8")
 def serve_content_stream(self,user,instance_id,timeout=25):
  first=content_view(user,instance_id)
  self.send_response(200);self.send_header("Content-Type","text/event-stream; charset=utf-8");self.send_header("Cache-Control","no-cache, no-transform");self.send_header("Connection","keep-alive");self.send_header("X-Accel-Buffering","no");self.send_header("X-Content-Type-Options","nosniff");self.end_headers()
  deadline=time.monotonic()+max(5,min(int(timeout),30));last_ping=0.0;last_signature=""
  try:
   self.wfile.write(sse_frame("ready",{"kind":"CapivaraCustomerContentStream","version":1,"retry_ms":1500}));self.wfile.flush()
   while time.monotonic()<deadline:
    payload=first if not last_signature else content_view(user,instance_id)
    encoded=json.dumps(to_json_compatible(payload),ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    signature=hashlib.sha256(encoded).hexdigest()
    if signature!=last_signature:
     self.wfile.write(sse_frame("content-state",payload,signature[:24]));self.wfile.flush();last_signature=signature;last_ping=time.monotonic()
    elif time.monotonic()-last_ping>=10:
     self.wfile.write(b": keepalive\n\n");self.wfile.flush();last_ping=time.monotonic()
    if not last_signature:first=None
    time.sleep(.75)
  except (BrokenPipeError,ConnectionResetError,OSError):
   return
 def error(self,exc):
  if isinstance(exc,PermissionError):return send(self,403,{"error":"forbidden","message":str(exc)})
  if isinstance(exc,KeyError):return send(self,404,{"error":"not_found","message":"Conteúdo não encontrado."})
  if isinstance(exc,(ValueError,LookupError)):return send(self,400,{"error":"invalid_request","message":str(exc)})
  internal=getattr(self,"_internal_error",None)
  if callable(internal):return internal(exc)
  return send(self,500,{"error":"content_failed","message":"Não foi possível concluir a operação de conteúdo."})
 def record(user,instance_id,action,content_id,result):
  try:
   api=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT);context=api.workspace.repo.instance_context(instance_id)
   InstanceActivityRepository(backend()).record(instance_id=instance_id,customer_id=context.get("customer_id"),username=str(user.get("username") or ""),role=str(user.get("role") or ""),activity=f"CONTENT_{action.upper()}_REQUESTED",category="content",result="accepted",target_type="content",target_name=content_id,details={"changed":bool(result.get("changed")),"revision":(result.get("assignment") or {}).get("revision")})
  except Exception:pass
 def record_policy(user,instance_id,activity,target,details):
  try:
   api=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT);context=api.workspace.repo.instance_context(instance_id)
   InstanceActivityRepository(backend()).record(instance_id=instance_id,customer_id=context.get("customer_id"),username=str(user.get("username") or ""),role=str(user.get("role") or ""),activity=activity,category="content",result="accepted",target_type="content_update_policy",target_name=target,details=details)
  except Exception:pass
 def policy_api(user,instance_id,permission="content.read"):
  api=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT);api.workspace.require(user,instance_id,permission);return api
 def get(self):
  parsed=urlparse(self.path)
  if parsed.path==STREAM:
   # EventSource cannot send X-Capivara-Auth-Area. Bind the stream explicitly
   # to the customer session boundary so a simultaneous Controller session
   # cannot shadow it in the same browser.
   user=require_user(self,area="customer")
   if user is None:return
   try:
    instance_id=iid(parsed)
    if not instance_id:raise ValueError("instance_id is required")
    return serve_content_stream(self,user,instance_id)
   except Exception as exc:return error(self,exc)
  if parsed.path==UPLOAD_STATUS:
   user=require_user(self)
   if user is None:return
   try:return send(self,200,{"transfer":transfer_view(CustomerContentUploadService(backend(),legacy.DSM_ROOT).status(user,one(parsed,"transfer_id")))})
   except Exception as exc:return error(self,exc)
  if parsed.path==SEARCH:
   user=require_user(self)
   if user is None:return
   try:
    api=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT);result=api.search_result(user,iid(parsed),one(parsed,"provider"),one(parsed,"content_type"),one(parsed,"q"),one(parsed,"limit","20"));return send(self,200,result)
   except Exception as exc:return error(self,exc)
  if parsed.path==ICON:
   user=require_user(self)
   if user is None:return
   try:
    instance_id=iid(parsed)
    if not instance_id:raise ValueError("instance_id is required")
    api=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT);api.workspace.require(user,instance_id,"content.read")
    content_type,data=_fetch_content_icon(one(parsed,"url"))
    self.send_response(200);self.send_header("Content-Type",content_type);self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","private, max-age=86400");self.send_header("X-Content-Type-Options","nosniff");self.end_headers();self.wfile.write(data);return
   except Exception as exc:return error(self,exc)
  if parsed.path==BUNDLE:
   user=require_user(self)
   if user is None:return
   try:
    instance_id=iid(parsed);content_id=str(one(parsed,"content_id") or "").strip()
    if not content_id:raise ValueError("content_id is required")
    api=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT);return send(self,200,{"bundle":api.bundle_details(user,instance_id,content_id)})
   except Exception as exc:return error(self,exc)
  if parsed.path==UPDATE_POLICY:
   user=require_user(self)
   if user is None:return
   try:
    instance_id=iid(parsed);policy_api(user,instance_id);return send(self,200,instance_update_policy_view(instance_id,backend=backend()))
   except Exception as exc:return error(self,exc)
  if parsed.path!=PATH:return previous_get(self)
  user=require_user(self)
  if user is None:return
  try:
   instance_id=iid(parsed);send(self,200,content_view(user,instance_id))
  except Exception as exc:error(self,exc)
 def post(self):
  parsed=urlparse(self.path)
  if parsed.path==UPLOAD_URL:
   user=require_user(self)
   if user is None:return
   try:
    body=self.read_json_body();instance_id=iid(parsed,body);item=CustomerContentUploadService(backend(),legacy.DSM_ROOT).import_url(user,instance_id,body.get("url"));return send(self,201,{"transfer":transfer_view(item)})
   except Exception as exc:return error(self,exc)
  if parsed.path==UPLOAD:
   user=require_user(self)
   if user is None:return
   try:
    body=self.read_json_body();instance_id=iid(parsed,body);item=CustomerContentUploadService(backend(),legacy.DSM_ROOT).create(user,instance_id,body.get("filename"));return send(self,201,{"transfer":transfer_view(item)})
   except Exception as exc:return error(self,exc)
  if parsed.path==UPLOAD_FINALIZE:
   user=require_user(self)
   if user is None:return
   try:
    body=self.read_json_body();api=CustomerContentUploadService(backend(),legacy.DSM_ROOT);result=api.finalize(user,str(body.get("transfer_id") or ""),body);assignment=result.get("assignment") or {};record(user,str(assignment.get("instance_id") or body.get("instance_id") or ""),"upload",str(assignment.get("content_id") or body.get("content_id") or ""),result);return send(self,202,result)
   except Exception as exc:return error(self,exc)
  if parsed.path==UPLOAD_CANCEL:
   user=require_user(self)
   if user is None:return
   try:
    body=self.read_json_body();item=CustomerContentUploadService(backend(),legacy.DSM_ROOT).cancel(user,str(body.get("transfer_id") or ""));return send(self,200,{"transfer":transfer_view(item),"message":"Upload cancelado."})
   except Exception as exc:return error(self,exc)
  if parsed.path==UPDATE_POLICY:
   user=require_user(self)
   if user is None:return
   try:
    body=self.read_json_body();instance_id=iid(parsed,body);api=policy_api(user,instance_id,"content.install");api.workspace.require(user,instance_id,"settings.write");policy=body.get("policy")
    if not isinstance(policy,dict):raise ValueError("policy must be an object")
    actor=str(user.get("username") or user.get("id") or "customer");set_instance_update_policy({"instance_id":instance_id,"policy":policy},backend=backend(),root=legacy.DSM_ROOT,requested_by=actor);view=instance_update_policy_view(instance_id,backend=backend());record_policy(user,instance_id,"CONTENT_UPDATE_POLICY_CHANGED",instance_id,{"mode":view["policy"]["mode"],"timezone":view["policy"]["timezone"]});return send(self,200,view)
   except Exception as exc:return error(self,exc)
  if parsed.path==UPDATE_POLICY_ITEM:
   user=require_user(self)
   if user is None:return
   try:
    body=self.read_json_body();instance_id=iid(parsed,body);policy_api(user,instance_id,"content.install");content_id=str(body.get("content_id") or "").strip()
    if not content_id:raise ValueError("content_id is required")
    actor=str(user.get("username") or user.get("id") or "customer");repo=ServerUpdateRepository(backend());repo.initialize();item=repo.set_content_policy(instance_id=instance_id,content_id=content_id,mode=body.get("mode"),requested_by=actor);record_policy(user,instance_id,"CONTENT_UPDATE_OVERRIDE_CHANGED",content_id,{"mode":item["mode"],"effective_mode":item["effective_mode"]});return send(self,200,{"content_update_policy":item,"view":instance_update_policy_view(instance_id,backend=backend())})
   except Exception as exc:return error(self,exc)
  if parsed.path!=PATH:return previous_post(self)
  user=require_user(self)
  if user is None:return
  try:
   body=self.read_json_body();instance_id=iid(parsed,body);action=str(body.get("action") or "install").strip().lower();api=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT)
   if action=="install":result=api.install(user,instance_id,body)
   elif action=="prepare-clean":result=api.prepare_clean_for_version_change(user,instance_id)
   else:
    content_id=str(body.get("content_id") or "").strip()
    if not content_id:raise ValueError("content_id is required")
    result=api.mutate(user,instance_id,content_id,action,body)
   record(user,instance_id,action,str((result.get("assignment") or {}).get("content_id") or body.get("content_id") or ""),result);send(self,202,result)
  except Exception as exc:error(self,exc)
 def put(self):
  parsed=urlparse(self.path)
  if parsed.path!=UPLOAD:
   if previous_put is not None:return previous_put(self)
   return send(self,404,{"error":"not_found"})
  user=require_user(self)
  if user is None:return
  try:
   item=CustomerContentUploadService(backend(),legacy.DSM_ROOT).stage(user,one(parsed,"transfer_id"),self.rfile,content_length(self));return send(self,201,{"transfer":transfer_view(item)})
  except Exception as exc:return error(self,exc)
 legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post;legacy.DashboardHandler.do_PUT=put

__all__=["PATH","SEARCH","ICON","BUNDLE","UPLOAD","UPLOAD_URL","UPLOAD_STATUS","UPLOAD_FINALIZE","UPLOAD_CANCEL","UPDATE_POLICY","UPDATE_POLICY_ITEM","STREAM","install_customer_content_http"]
