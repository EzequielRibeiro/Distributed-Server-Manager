#!/usr/bin/env python3
"""Observed server configuration surface derived exclusively from Agent-owned RuntimeSpec."""
from __future__ import annotations
import csv, hashlib, io, json, re
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

_FILE_KINDS={"property","json","xml_property","ini"}
_SECRET_WORDS=("password","passwd","token","secret","apikey","api_key","credential","privatekey","private_key","licensekey","license_key","steamaccount","steam_account","authkey","auth_key","webapikey","web_api_key","clientsecret","client_secret")

_DAYZ_META={
 "respawntime":{"type":"integer","min":0,"group":"Servidor"},
 "motd[]":{"type":"string_list","group":"Servidor","max_items":64,"max_length":512},
 "motdinterval":{"type":"integer","min":0,"group":"Servidor"},
 "timestampformat":{"type":"string","allowed":["Short","Full"],"group":"Logging"},
 "logaveragefps":{"type":"integer","min":0,"group":"Logging","requires_argument":"-doLogs"},
 "logmemory":{"type":"integer","min":0,"group":"Logging","requires_argument":"-doLogs"},
 "logplayers":{"type":"integer","min":0,"group":"Logging","requires_argument":"-doLogs"},
 "logfile":{"type":"string","group":"Logging","safe_relative_path":True,"max_length":255},
 "adminlogplayerhitsonly":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Logging","requires_argument":"-adminLog"},
 "adminlogplacement":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Logging","requires_argument":"-adminLog"},
 "adminlogbuildactions":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Logging","requires_argument":"-adminLog"},
 "adminlogplayerlist":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Logging","requires_argument":"-adminLog"},
 "disablemultiaccountmitigation":{"type":"boolean","group":"Jogabilidade"},
 "enabledebugmonitor":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Jogabilidade"},
 "allowfilepatching":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Segurança"},
 "simulatedplayersbatch":{"type":"integer","min":1,"group":"Desempenho"},
 "multithreadedreplication":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Desempenho"},
 "speedhackdetection":{"type":"number","min":1,"max":10,"step":0.1,"group":"Segurança"},
 "networkrangeclose":{"type":"integer","min":0,"group":"Rede e desempenho"},
 "networkrangenear":{"type":"integer","min":0,"group":"Rede e desempenho"},
 "networkrangefar":{"type":"integer","min":0,"group":"Rede e desempenho"},
 "networkrangedistanteffect":{"type":"integer","min":0,"group":"Rede e desempenho"},
 "networkobjectbatchlogslow":{"type":"number","min":0,"group":"Rede e desempenho"},
 "networkobjectbatchenforcebandwidthlimits":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Rede e desempenho"},
 "networkobjectbatchuseestimatedbandwidth":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Rede e desempenho"},
 "networkobjectbatchusedynamicmaximumbandwidth":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Rede e desempenho"},
 "networkobjectbatchbandwidthlimit":{"type":"number","min":0,"step":0.01,"group":"Rede e desempenho"},
 "networkobjectbatchcompute":{"type":"integer","min":1,"group":"Rede e desempenho"},
 "networkobjectbatchsendcreate":{"type":"integer","min":1,"group":"Rede e desempenho"},
 "networkobjectbatchsenddelete":{"type":"integer","min":1,"group":"Rede e desempenho"},
 "defaultvisibility":{"type":"integer","min":0,"group":"Renderização"},
 "defaultobjectviewdistance":{"type":"integer","min":0,"group":"Renderização"},
 "lightingconfig":{"type":"integer","allowed":[0,1,2],"group":"Jogabilidade"},
 "disablepersonallight":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Jogabilidade"},
 "disablebasedamage":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Jogabilidade"},
 "disablecontainerdamage":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Jogabilidade"},
 "disablerespawndialog":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Jogabilidade"},
 "pingwarning":{"type":"integer","min":0,"group":"Limites de conexão"},
 "pingcritical":{"type":"integer","min":0,"group":"Limites de conexão"},
 "maxping":{"type":"integer","min":0,"group":"Limites de conexão"},
 "serverfpswarning":{"type":"integer","min":11,"group":"Limites de conexão"},
 "shotvalidation":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Segurança"},
 "enablewhitelist":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Servidor"},
 "forcesamebuild":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Segurança"},
 "disablevon":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Jogabilidade"},
 "voncodecquality":{"type":"integer","min":0,"max":30,"group":"Jogabilidade"},
 "disable3rdperson":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Jogabilidade"},
 "disablecrosshair":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Jogabilidade"},
 "servertimeacceleration":{"type":"number","min":0,"max":24,"group":"Tempo"},
 "servernighttimeacceleration":{"type":"number","min":0.1,"max":64,"group":"Tempo"},
 "servertimepersistent":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Tempo"},
 "storageautofix":{"type":"boolean","boolean_values":{"true":"1","false":"0"},"group":"Servidor"},
}

def _scalar_type(value:Any)->str:
 if isinstance(value,bool):return "boolean"
 if isinstance(value,int) and not isinstance(value,bool):return "integer"
 if isinstance(value,float):return "number"
 text=str(value).strip()
 if text.lower() in {"true","false"}:return "boolean"
 if re.fullmatch(r"[-+]?\d+",text):return "integer"
 if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)",text):return "number"
 return "string"

def _coerce(raw:Any,kind:str)->Any:
 if kind=="string_list":
  if not isinstance(raw,list):raise ValueError("server setting must be a string list")
  if len(raw)>128:raise ValueError("server setting list is too long")
  out=[]
  for item in raw:
   text=str(item)
   if any(ch in text for ch in ("\x00","\r","\n")) or len(text)>8192:raise ValueError("invalid server setting list item")
   out.append(text)
  return out
 if kind=="boolean":
  if isinstance(raw,bool):return raw
  text=str(raw).strip().lower()
  if text in {"true","1","yes","on"}:return True
  if text in {"false","0","no","off"}:return False
  raise ValueError("invalid boolean server setting")
 if kind=="integer":
  if isinstance(raw,bool):raise ValueError("invalid integer server setting")
  return int(raw)
 if kind=="number":
  if isinstance(raw,bool):raise ValueError("invalid numeric server setting")
  return float(raw)
 text=str(raw)
 if any(ch in text for ch in ("\x00","\r","\n")):raise ValueError("invalid server setting text")
 if len(text)>8192:raise ValueError("server setting value is too long")
 return text

def _render(value:Any,kind:str,*,quoted:bool=False)->str:
 if kind=="boolean":text="true" if bool(value) else "false"
 elif kind in {"integer","number"}:text=str(value)
 else:text=str(value)
 return json.dumps(text,ensure_ascii=False) if quoted else text

def _secret(key:str)->bool:
 compact=re.sub(r"[^a-z0-9_]","",str(key).lower())
 return any(word in compact for word in _SECRET_WORDS)

def _platform_managed(key:str,src:dict[str,Any]|None=None)->bool:
 raw=str(key or "").strip();compact=re.sub(r"[^a-z0-9]","",raw.lower())
 common={"port","serverport","serverportv6","queryport","steamqueryport","rconport","publicport","bindport","gameport","gamequeryport","a2sport","steamport","bindaddress","publicaddress","serverip","bindip","publicip","endpointaddudp","endpointaddtcp"}
 if compact in common:return True
 if re.search(r"(?:^|[_-])(bind|public|query|steam|rcon|a2s|game)[_-]?port$",raw,re.I):return True
 context=src if isinstance(src,dict) else {}
 runtime_id=str(context.get("runtime_id") or "").strip().lower()
 path=str(context.get("path") or "").strip().replace("\\","/").lower()
 if runtime_id.startswith("dayz") and path=="serverdz.cfg" and compact=="template":return True
 return False

def _field_id(path:str,fmt:str,locator:str)->str:
 digest=hashlib.sha256(f"{path}\0{fmt}\0{locator}".encode()).hexdigest()[:24]
 return f"cfg-{digest}"

def _root(spec:dict[str,Any])->Path:
 raw=str(spec.get("configuration_root") or "").strip()
 if not raw:
  config_path=str(spec.get("config_path") or "").strip()
  if config_path and Path(config_path).is_absolute():raw=str(Path(config_path).parent)
 if not raw:
  working=str(spec.get("working_directory") or spec.get("path") or "").strip()
  if working and Path(working).is_absolute():raw=working
 if not raw or not Path(raw).is_absolute():raise ValueError("server settings require an absolute configuration root")
 return Path(raw).resolve(strict=False)

def _target(root:Path,relative:str)->Path:
 rel=Path(str(relative or "").replace("\\","/"))
 if not str(rel) or rel.is_absolute() or ".." in rel.parts:raise ValueError("invalid server setting path")
 target=(root/rel).resolve(strict=False);target.relative_to(root)
 if target.is_symlink():raise ValueError("server setting target cannot be a link")
 return target

def _atomic_text(target:Path,text:str)->None:
 import os,tempfile
 target.parent.mkdir(parents=True,exist_ok=True)
 try:st=target.stat();uid=getattr(st,"st_uid",None);gid=getattr(st,"st_gid",None);mode=st.st_mode&0o777
 except FileNotFoundError:uid=gid=None;mode=0o600
 fd,tmp=tempfile.mkstemp(prefix=f".{target.name}.",dir=str(target.parent),text=True)
 try:
  with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as stream:stream.write(text);stream.flush();os.fsync(stream.fileno())
  os.chmod(tmp,mode)
  if hasattr(os,"chown") and uid is not None and gid is not None:
   try:os.chown(tmp,uid,gid)
   except (PermissionError,OSError):pass
  os.replace(tmp,target)
 finally:
  try:os.unlink(tmp)
  except FileNotFoundError:pass

def _sources(spec:dict[str,Any])->dict[str,dict[str,Any]]:
 runtime_id=str(spec.get("environment_id") or spec.get("runtime_id") or "").lower()
 result={};decl=spec.get("catalog_server_settings") if isinstance(spec.get("catalog_server_settings"),dict) else {}
 for logical,field in (decl.get("fields") or {}).items():
  if not isinstance(field,dict):continue
  binding=field.get("binding") if isinstance(field.get("binding"),dict) else {};kind=str(binding.get("kind") or "")
  path=str(binding.get("path") or "").strip()
  if kind in _FILE_KINDS and path:
   src=result.setdefault(path,{"path":path,"kinds":set(),"known":{},"managed":set(),"runtime_id":runtime_id});src["kinds"].add(kind)
   locator=_binding_locator(binding)
   if locator:src["known"][locator]=(str(logical),field,binding)
 for item in spec.get("catalog_network_properties") or []:
  if not isinstance(item,dict):continue
  path=str(item.get("path") or "").strip();key=str(item.get("key") or "").strip()
  if path and key:
   src=result.setdefault(path,{"path":path,"kinds":set(),"known":{},"managed":set(),"runtime_id":runtime_id});src["kinds"].add("property");src["managed"].add(key.lower())
 return result

def _binding_locator(binding:dict[str,Any])->str:
 kind=str(binding.get("kind") or "")
 if kind=="json":return "/".join(str(x) for x in (binding.get("keys") or []))
 if kind=="ini":return f"{binding.get('section','')}::{binding.get('key','')}"
 return str(binding.get("key") or "")

def _known_meta(src:dict[str,Any],locator:str):
 exact=src.get("known",{}).get(locator)
 if exact:return exact
 low=locator.lower()
 for key,value in src.get("known",{}).items():
  if str(key).lower()==low:return value
 return None

def _semantic(src:dict[str,Any],key:str)->dict[str,Any]:
 runtime_id=str(src.get("runtime_id") or "").lower()
 if runtime_id.startswith("dayz") and str(src.get("path") or "").lower()=="serverdz.cfg":return dict(_DAYZ_META.get(str(key).lower()) or {})
 return {}

def _field(path:str,fmt:str,locator:str,key:str,value:Any,src:dict[str,Any],*,section:str|None=None,occurrence:int=0,raw_quote:bool=False)->dict[str,Any]:
 known=_known_meta(src,locator);logical=None;decl={};binding={}
 if known:logical,decl,binding=known
 semantic=_semantic(src,key);kind=str(decl.get("type") or semantic.get("type") or _scalar_type(value)).lower()
 if kind=="select":kind="string"
 boolean_values=semantic.get("boolean_values") if isinstance(semantic.get("boolean_values"),dict) else None
 if kind=="boolean" and boolean_values and not isinstance(value,bool):
  text=str(value);value=True if text==str(boolean_values.get("true")) else False if text==str(boolean_values.get("false")) else _coerce(value,"boolean")
 secret=_secret(key);managed=str(key).lower() in src.get("managed",set()) or _platform_managed(key,src)
 editable=not managed and not secret
 item={"id":_field_id(path,fmt,f"{locator}#{occurrence}"),"path":path,"format":fmt,"key":key,"label":str(decl.get("label") or key),"type":kind,"editable":editable,"managed":managed,"secret":secret,"logical_id":logical,"section":section,"occurrence":occurrence,"locator":locator,"quoted":raw_quote}
 if decl.get("description"):item["description"]=decl["description"]
 for name in ("min","max","max_length","allowed","step","group","requires_argument","safe_relative_path","max_items","boolean_values"):
  if name in decl:item[name]=decl[name]
  elif name in semantic:item[name]=semantic[name]
 if secret:item["has_value"]=value not in {None,""};item["value"]=None
 else:item["value"]=value
 return item

def _strip_inline_comment(text:str)->str:
 quoted=False;escaped=False
 for index,ch in enumerate(text):
  if quoted:
   if escaped:escaped=False
   elif ch=="\\":escaped=True
   elif ch=='"':quoted=False
   continue
  if ch=='"':quoted=True;continue
  if ch=='#':return text[:index].rstrip()
  if ch=='/' and index+1<len(text) and text[index+1]=='/':return text[:index].rstrip()
 return text.rstrip()

def _unquote(text:str)->tuple[str,bool]:
 value=_strip_inline_comment(text).strip()
 if len(value)>=2 and value[0]==value[-1]=='"':
  try:return json.loads(value),True
  except Exception:return value[1:-1],True
 return value,False

def _parse_property(path:str,text:str,src:dict[str,Any],syntax:str)->list[dict[str,Any]]:
 if syntax=="ue_option_settings":return _parse_ue(path,text,src)
 out=[];seen={}
 if syntax=="command":
  pattern=re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_.:-]*)\s+(.*?)\s*$')
 else:
  pattern=re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_.:-]*)\s*=\s*(.*?)\s*;?\s*(?://.*|#.*)?$')
 for line in text.splitlines():
  stripped=line.strip()
  if not stripped or stripped.startswith(("#","//",";")):continue
  if syntax!="command":
   array_match=re.match(r'^\s*([A-Za-z_][A-Za-z0-9_.:-]*)\[\]\s*=\s*\{(.*?)\}\s*;?\s*(?://.*|#.*)?$',line)
   if array_match:
    key=array_match.group(1)+"[]";body=array_match.group(2).strip();items=[]
    if body:
     try:items=[str(item) for item in next(csv.reader(io.StringIO(body),delimiter=',',quotechar='"',escapechar='\\'))]
     except Exception:items=[]
    occ=seen.get(key.lower(),0);seen[key.lower()]=occ+1
    out.append(_field(path,"string_list",key,key,items,src,occurrence=occ));continue
  m=pattern.match(line)
  if not m:continue
  key=m.group(1);raw=m.group(2).strip()
  if syntax!="command" and raw.endswith(";"):raw=raw[:-1].rstrip()
  value,quoted=_unquote(raw);kind=_scalar_type(value)
  try:value=_coerce(value,kind)
  except Exception:kind="string";value=str(value)
  occ=seen.get(key.lower(),0);seen[key.lower()]=occ+1
  out.append(_field(path,"command" if syntax=="command" else ("semicolon" if syntax=="semicolon" else "equals"),key,key,value,src,occurrence=occ,raw_quote=quoted))
 return out

def _split_ue(body:str)->list[str]:
 reader=csv.reader(io.StringIO(body),delimiter=',',quotechar='"',escapechar='\\')
 return next(reader,[])

def _parse_ue(path:str,text:str,src:dict[str,Any])->list[dict[str,Any]]:
 m=re.search(r"OptionSettings\s*=\s*\((.*)\)\s*$",text,re.S)
 if not m:return []
 out=[]
 for token in _split_ue(m.group(1)):
  key,sep,raw=token.partition('=')
  if not sep:continue
  key=key.strip();value,quoted=_unquote(raw.strip());kind=_scalar_type(value)
  try:value=_coerce(value,kind)
  except Exception:kind="string";value=str(value)
  out.append(_field(path,"ue_option_settings",key,key,value,src,raw_quote=quoted))
 return out

def _parse_json(path:str,text:str,src:dict[str,Any])->list[dict[str,Any]]:
 try:data=json.loads(text) if text.strip() else {}
 except json.JSONDecodeError as exc:raise ValueError(f"invalid JSON configuration: {path}") from exc
 out=[]
 def walk(value,prefix):
  if isinstance(value,dict):
   for k,v in value.items():walk(v,[*prefix,str(k)])
  elif isinstance(value,list):
   for i,v in enumerate(value):walk(v,[*prefix,str(i)])
  else:
   locator='/'.join(prefix);key=prefix[-1] if prefix else 'value';out.append(_field(path,"json",locator,key,value,src,section='/'.join(prefix[:-1]) or None))
 walk(data,[]);return out

def _parse_ini(path:str,text:str,src:dict[str,Any])->list[dict[str,Any]]:
 out=[];section="";seen={}
 for line in text.splitlines():
  stripped=line.strip()
  if not stripped or stripped.startswith(("#",";","//")):continue
  if stripped.startswith('[') and stripped.endswith(']'):section=stripped[1:-1].strip();continue
  if '=' not in line:continue
  key,raw=line.split('=',1);key=key.strip();value,quoted=_unquote(raw.strip());kind=_scalar_type(value)
  try:value=_coerce(value,kind)
  except Exception:kind="string";value=str(value)
  locator=f"{section}::{key}";counter=locator.lower();occ=seen.get(counter,0);seen[counter]=occ+1
  out.append(_field(path,"ini",locator,key,value,src,section=section or None,occurrence=occ,raw_quote=quoted))
 return out

def _parse_xml(path:str,text:str,src:dict[str,Any])->list[dict[str,Any]]:
 try:root=ET.fromstring(text)
 except ET.ParseError as exc:raise ValueError(f"invalid XML configuration: {path}") from exc
 out=[];seen={}
 for node in root.findall('.//property'):
  key=str(node.attrib.get('name') or '').strip()
  if not key:continue
  value=str(node.attrib.get('value') or '');kind=_scalar_type(value)
  try:value=_coerce(value,kind)
  except Exception:kind="string"
  occ=seen.get(key.lower(),0);seen[key.lower()]=occ+1
  out.append(_field(path,"xml_property",key,key,value,src,occurrence=occ))
 return out

def _syntax_for(src:dict[str,Any])->str:
 for _logical,_decl,binding in src.get("known",{}).values():
  syntax=str(binding.get("syntax") or "")
  if syntax:return syntax
 kinds=src.get("kinds",set())
 if "json" in kinds:return "json"
 if "xml_property" in kinds:return "xml_property"
 if "ini" in kinds:return "ini"
 return "equals"

def observed_surface(spec:dict[str,Any])->dict[str,Any]:
 root=_root(spec);files=[];fields=[]
 for path,src in sorted(_sources(spec).items()):
  target=_target(root,path);syntax=_syntax_for(src);exists=target.is_file();text=target.read_text(encoding='utf-8',errors='replace') if exists else ''
  if syntax=="json":items=_parse_json(path,text,src)
  elif syntax=="xml_property":items=_parse_xml(path,text,src) if exists else []
  elif syntax=="ini":items=_parse_ini(path,text,src)
  else:items=_parse_property(path,text,src,syntax)
  files.append({"path":path,"format":syntax,"exists":exists,"field_count":len(items)});fields.extend(items)
 # A config file may already contain duplicate catalog-owned keys from an older materializer.
 # Present only the effective last occurrence; the current writer canonicalizes duplicates on save.
 last_logical={}
 for index,item in enumerate(fields):
  logical=str(item.get("logical_id") or "").strip()
  if logical:last_logical[logical]=index
 fields=[item for index,item in enumerate(fields) if not item.get("logical_id") or last_logical.get(str(item.get("logical_id")))==index]
 # Fallback for launch/command settings that have no configuration file.
 decl=spec.get("catalog_server_settings") if isinstance(spec.get("catalog_server_settings"),dict) else {}
 args=list(spec.get("arguments") or [])
 for logical,entry in (decl.get("fields") or {}).items():
  if not isinstance(entry,dict):continue
  binding=entry.get("binding") if isinstance(entry.get("binding"),dict) else {};kind=str(binding.get("kind") or "")
  if kind in _FILE_KINDS:continue
  value=_argument_value(args,binding)
  if value is None:continue
  value=_declared_value(value,entry,binding);typ=str(entry.get("type") or _scalar_type(value));fid=_field_id("@launcher",kind,str(logical));secret=_secret(str(logical))
  item={"id":fid,"path":"@launcher","format":kind,"key":str(logical),"label":str(entry.get("label") or logical),"type":typ,"editable":not secret,"managed":False,"secret":secret,"logical_id":str(logical),"locator":str(logical),"value":None if secret else value,"has_value":bool(value) if secret else None}
  for name in ("min","max","max_length","allowed","description"):
   if name in entry:item[name]=entry[name]
  fields.append(item)
 return {"schema_version":1,"kind":"CapivaraObservedServerSettings","runtime_id":str(spec.get("environment_id") or spec.get("runtime_id") or ''),"files":files,"fields":fields,"restart_required":bool(decl.get("restart_required",True))}

def _declared_value(raw:Any,decl:dict[str,Any],binding:dict[str,Any])->Any:
 kind=str(decl.get("type") or _scalar_type(raw)).lower()
 if kind=="boolean":
  mapping=binding.get("boolean_values") if isinstance(binding.get("boolean_values"),dict) else {}
  text=str(raw)
  if mapping and text==str(mapping.get("true")):return True
  if mapping and text==str(mapping.get("false")):return False
  return _coerce(raw,"boolean")
 if kind=="integer":return _coerce(raw,"integer")
 if kind=="number":return _coerce(raw,"number")
 return raw

def _argument_value(args:list[str],binding:dict[str,Any]):
 kind=str(binding.get("kind") or '')
 if kind=="argument":
  flag=str(binding.get('flag') or '');style=str(binding.get('style') or 'pair')
  for i,item in enumerate(args):
   if style=="equals" and str(item).lower().startswith((flag+'=').lower()):return str(item).split('=',1)[1]
   if str(item).lower()==flag.lower() and i+1<len(args):return args[i+1]
 if kind=="launch_option":
  idx=int(binding.get('argument_index',0));key=str(binding.get('key') or '')
  if idx<len(args):
   for token in str(args[idx]).split('?')[1:]:
    name,sep,value=token.partition('=')
    if sep and name.lower()==key.lower():return value
 if kind=="command_batch":
  idx=int(binding.get('argument_index',2));command=str(binding.get('command') or '').strip()
  if idx<len(args):
   for token in str(args[idx]).split(str(binding.get('separator') or ',')):
    token=token.strip()
    if token.lower().startswith(command.lower()+' '):return token[len(command):].strip().strip('"')
 return None

def normalize_dynamic_values(spec:dict[str,Any],values:dict[str,Any],*,player_limit:int|None=None)->dict[str,Any]:
 if not isinstance(values,dict):raise ValueError("dynamic server settings must be an object")
 surface=observed_surface(spec);by_id={f['id']:f for f in surface['fields'] if not f.get('logical_id') and f.get('path')!='@launcher'};out={}
 for fid,raw in values.items():
  field=by_id.get(str(fid))
  if field is None:raise PermissionError("unknown or catalog-owned server setting")
  if not field.get('editable'):raise PermissionError("server setting is managed by Capivara")
  value=_coerce(raw,str(field.get('type') or 'string'))
  if field.get("min") is not None and isinstance(value,(int,float)) and value<float(field["min"]):raise ValueError("server setting below minimum")
  if field.get("max") is not None and isinstance(value,(int,float)) and value>float(field["max"]):raise ValueError("server setting above maximum")
  allowed=field.get("allowed")
  if isinstance(allowed,list) and allowed and value not in allowed:raise ValueError("invalid server setting value")
  if field.get("safe_relative_path"):
   candidate=Path(str(value));
   if candidate.is_absolute() or ".." in candidate.parts:raise ValueError("server setting path must stay relative")
  if str(field.get("type"))=="string_list":
   if field.get("max_items") is not None and len(value)>int(field["max_items"]):raise ValueError("too many server setting list items")
   if field.get("max_length") is not None and any(len(x)>int(field["max_length"]) for x in value):raise ValueError("server setting list item is too long")
  out[str(fid)]=value
 validate_dynamic_relationships(spec,out)
 return out

def _replace_nth(lines:list[str],matcher,replacement:str,occurrence:int)->list[str]:
 count=0
 for i,line in enumerate(lines):
  if matcher(line):
   if count==occurrence:lines[i]=replacement;return lines
   count+=1
 raise KeyError("server setting field disappeared")

def _comment_parts(line:str)->tuple[str,str]:
 quoted=False;escaped=False
 for index,ch in enumerate(line):
  if quoted:
   if escaped:escaped=False
   elif ch=="\\":escaped=True
   elif ch=='"':quoted=False
   continue
  if ch=='"':quoted=True;continue
  if ch=='#':return line[:index],line[index:]
  if ch=='/' and index+1<len(line) and line[index+1]=='/':return line[:index],line[index:]
 return line,""

def _render_dynamic(field:dict[str,Any],value:Any)->str:
 kind=str(field.get("type") or "string")
 if kind=="boolean" and isinstance(field.get("boolean_values"),dict):
  mapping=field["boolean_values"];return str(mapping["true"] if value else mapping["false"])
 return _render(value,kind,quoted=bool(field.get("quoted")))

def _preserve_assignment(line:str,key:str,rendered:str,fmt:str)->str:
 body,comment=_comment_parts(line);suffix=(" " if comment and body and not body.endswith((" ","\t")) else "")+comment
 if fmt=="semicolon":
  m=re.match(rf'^(\s*{re.escape(key)}\s*=\s*)(.*?)(\s*;\s*)$',body)
  if m:return m.group(1)+rendered+m.group(3)+suffix
 if fmt=="equals":
  m=re.match(rf'^(\s*{re.escape(key)}\s*=\s*)(.*?)\s*$',body)
  if m:return m.group(1)+rendered+(" " if comment else "")+comment
 if fmt=="command":
  m=re.match(rf'^(\s*{re.escape(key)}\s+)(.*?)\s*$',body)
  if m:return m.group(1)+rendered+(" " if comment else "")+comment
 return (f"{key} = {rendered};" if fmt=="semicolon" else f"{key}={rendered}")+suffix

def _apply_field(root:Path,field:dict[str,Any],value:Any)->None:
 target=_target(root,str(field['path']));fmt=str(field['format']);key=str(field['key']);occ=int(field.get('occurrence') or 0);kind=str(field.get('type') or 'string');quoted=bool(field.get('quoted'))
 if fmt=="json":
  data=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {};parts=str(field['locator']).split('/');cursor=data
  for part in parts[:-1]:cursor=cursor[int(part)] if isinstance(cursor,list) else cursor[part]
  last=parts[-1]
  if isinstance(cursor,list):cursor[int(last)]=value
  else:cursor[last]=value
  _atomic_text(target,json.dumps(data,indent=2,sort_keys=True,ensure_ascii=False)+'\n');return
 if fmt=="xml_property":
  tree=ET.parse(target);root_xml=tree.getroot();matches=[n for n in root_xml.findall('.//property') if str(n.attrib.get('name') or '').lower()==key.lower()]
  if occ>=len(matches):raise KeyError("server setting field disappeared")
  matches[occ].set('value',_render(value,kind));_atomic_text(target,'<?xml version="1.0" encoding="utf-8"?>\n'+ET.tostring(root_xml,encoding='unicode')+'\n');return
 if fmt=="ue_option_settings":
  text=target.read_text(encoding='utf-8',errors='replace');pattern=re.compile(rf"(?<![A-Za-z0-9_]){re.escape(key)}\s*=\s*(?:\"(?:\\.|[^\"])*\"|[^,)]*)");rendered=_render(value,kind,quoted=quoted or kind=='string');_atomic_text(target,pattern.sub(f"{key}={rendered}",text,count=1));return
 lines=target.read_text(encoding='utf-8',errors='replace').splitlines();rendered=_render_dynamic(field,value)
 if fmt=="string_list":
  base=key[:-2] if key.endswith("[]") else key;matcher=lambda line: re.match(rf"^\s*{re.escape(base)}\[\]\s*=",line,re.I) is not None
  body=", ".join(json.dumps(str(item),ensure_ascii=False) for item in value)
  count=0
  for i,line in enumerate(lines):
   if matcher(line):
    if count==occ:
     before,comment=_comment_parts(line);prefix=re.match(rf'^(\s*{re.escape(base)}\[\]\s*=\s*)',before).group(1);lines[i]=prefix+"{ "+body+" };"+(" "+comment if comment else "");break
    count+=1
  else:raise KeyError("server setting field disappeared")
  _atomic_text(target,'\n'.join(lines)+'\n');return
 if fmt=="ini":
  section=str(field.get('section') or '');current=''
  def matcher(line):
   nonlocal current
   s=line.strip()
   if s.startswith('[') and s.endswith(']'):current=s[1:-1].strip();return False
   return current.lower()==section.lower() and re.match(rf"^\s*{re.escape(key)}\s*=",line,re.I) is not None
  replacement=f"{key}={rendered}"
 elif fmt=="command":
  matcher=lambda line: re.match(rf"^\s*{re.escape(key)}\s+",line,re.I) is not None;replacement=None
 else:
  matcher=lambda line: re.match(rf"^\s*{re.escape(key)}\s*=",line,re.I) is not None;replacement=None
 if replacement is not None:lines=_replace_nth(lines,matcher,replacement,occ)
 else:
  count=0
  for i,line in enumerate(lines):
   if matcher(line):
    if count==occ:lines[i]=_preserve_assignment(line,key,rendered,fmt);break
    count+=1
  else:raise KeyError("server setting field disappeared")
 _atomic_text(target,'\n'.join(lines)+'\n')

def apply_runtime_dependencies(spec:dict[str,Any])->dict[str,Any]:
 result=dict(spec);values=result.get("server_settings_dynamic_values") if isinstance(result.get("server_settings_dynamic_values"),dict) else {}
 previous=[str(x) for x in (result.get("server_settings_dependency_arguments") or [])];args=[str(x) for x in (result.get("arguments") or []) if str(x) not in previous];surface=observed_surface(result);by_id={f["id"]:f for f in surface.get("fields") or []}
 required=[]
 for fid,value in values.items():
  field=by_id.get(str(fid));flag=str((field or {}).get("requires_argument") or "")
  if not flag:continue
  enabled=(bool(value) if isinstance(value,bool) else float(value)>0 if isinstance(value,(int,float)) else bool(str(value).strip()))
  if enabled and flag not in args and flag not in required:required.append(flag)
 result["arguments"]=[*args,*required];result["server_settings_dependency_arguments"]=required
 return result

def validate_dynamic_relationships(spec:dict[str,Any],values:dict[str,Any])->None:
 surface=observed_surface(spec);by_id={f["id"]:f for f in surface.get("fields") or []};by_key={}
 for fid,value in values.items():
  field=by_id.get(str(fid));
  if field:by_key[str(field.get("key") or "").lower()]=value
 warning=by_key.get("pingwarning");critical=by_key.get("pingcritical");maximum=by_key.get("maxping")
 if warning is not None and critical is not None and float(warning)>float(critical):raise ValueError("pingWarning must be less than or equal to pingCritical")
 if critical is not None and maximum is not None and float(critical)>float(maximum):raise ValueError("pingCritical must be less than or equal to MaxPing")

def materialize_dynamic_values(spec:dict[str,Any])->list[str]:
 values=spec.get('server_settings_dynamic_values') if isinstance(spec.get('server_settings_dynamic_values'),dict) else {}
 if not values:return []
 surface=observed_surface(spec);by_id={f['id']:f for f in surface['fields'] if not f.get('logical_id') and f.get('path')!='@launcher'};root=_root(spec);written=[]
 for fid,value in values.items():
  field=by_id.get(str(fid))
  if field is None:raise PermissionError("dynamic server setting no longer exists")
  if not field.get('editable'):raise PermissionError("dynamic server setting is managed by Capivara")
  _apply_field(root,field,_coerce(value,str(field.get('type') or 'string')));written.append(str(field['path']))
 return sorted(set(written))

__all__=["apply_runtime_dependencies","materialize_dynamic_values","normalize_dynamic_values","observed_surface","validate_dynamic_relationships"]
