#!/usr/bin/env python3
"""Apply catalog-declared customer server settings without accepting browser-owned bindings."""
from __future__ import annotations
import json, os, re, tempfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

_FILE_KINDS={"property","json","xml_property","ini"}
_ARG_KINDS={"argument","launch_option","command_batch"}

def _is_link(path:Path)->bool:
    try:
        if path.is_symlink(): return True
        checker=getattr(path,"is_junction",None)
        return bool(checker and checker())
    except OSError:return True

def _root(spec:dict[str,Any])->Path:
    raw=str(spec.get("configuration_root") or "").strip()
    if not raw or not Path(raw).is_absolute():raise ValueError("server settings require an absolute configuration_root")
    root=Path(raw).resolve(strict=False)
    if root.exists() and _is_link(root):raise ValueError("configuration_root cannot be a link")
    root.mkdir(parents=True,exist_ok=True)
    return root

def _target(root:Path,relative:str)->Path:
    rel=Path(str(relative or "").replace("\\","/"))
    if not str(rel) or rel.is_absolute() or ".." in rel.parts:raise ValueError("invalid server setting path")
    target=(root/rel).resolve(strict=False)
    target.relative_to(root)
    current=root
    for part in rel.parts[:-1]:
        current=current/part
        if current.exists() and _is_link(current):raise ValueError("server setting path traverses a link")
        current.mkdir(exist_ok=True)
    if target.exists() and _is_link(target):raise ValueError("server setting target cannot be a link")
    return target

def _owner_mode(target:Path)->tuple[int|None,int|None,int]:
    try:st=target.stat();return getattr(st,"st_uid",None),getattr(st,"st_gid",None),st.st_mode&0o777
    except FileNotFoundError:
        try:st=target.parent.stat();return getattr(st,"st_uid",None),getattr(st,"st_gid",None),0o600
        except OSError:return None,None,0o600

def _atomic_text(target:Path,text:str)->None:
    target.parent.mkdir(parents=True,exist_ok=True);uid,gid,mode=_owner_mode(target)
    fd,name=tempfile.mkstemp(prefix=f".{target.name}.",dir=str(target.parent),text=True)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.chmod(name,mode)
        if hasattr(os,"chown") and uid is not None and gid is not None:
            try:os.chown(name,uid,gid)
            except PermissionError:pass
        os.replace(name,target)
    finally:
        try:os.unlink(name)
        except FileNotFoundError:pass

def _coerce(field_id:str,spec:dict[str,Any],value:Any)->Any:
    kind=str(spec.get("type") or "string").lower()
    if kind=="boolean":
        if not isinstance(value,bool):raise ValueError(f"server setting must be boolean: {field_id}")
        return value
    if kind=="integer":
        if isinstance(value,bool):raise ValueError(f"server setting must be integer: {field_id}")
        try:value=int(value)
        except (TypeError,ValueError) as exc:raise ValueError(f"server setting must be integer: {field_id}") from exc
        if spec.get("min") is not None and value<int(spec["min"]):raise ValueError(f"server setting below minimum: {field_id}")
        if spec.get("max") is not None and value>int(spec["max"]):raise ValueError(f"server setting above maximum: {field_id}")
        return value
    if kind=="select":
        if value not in list(spec.get("allowed") or []):raise ValueError(f"invalid server setting value: {field_id}")
        return value
    text=str(value)
    if any(ch in text for ch in ("\x00","\r","\n")):raise ValueError(f"invalid server setting text: {field_id}")
    if len(text)>int(spec.get("max_length") or 256):raise ValueError(f"server setting too long: {field_id}")
    return text

def _binding_value(binding:dict[str,Any],value:Any)->str:
    if isinstance(value,bool):
        mapping=binding.get("boolean_values") if isinstance(binding.get("boolean_values"),dict) else None
        text=str(mapping["true"] if value else mapping["false"]) if mapping else ("true" if value else "false")
    else:text=str(value)
    if any(ch in text for ch in ("\x00","\r","\n")):raise ValueError("invalid materialized server setting")
    quote=str(binding.get("quote") or "none").lower()
    if quote=="double":return json.dumps(text,ensure_ascii=False)
    if quote not in {"none",""}:raise ValueError("unsupported server setting quote mode")
    return text

def _ue_bounds(text:str)->tuple[int,int]:
    match=re.search(r"OptionSettings\s*=\s*\(",text)
    if not match:raise ValueError("Unreal OptionSettings entry is unavailable")
    start=match.end();depth=1;quoted=False;escaped=False
    for index in range(start,len(text)):
        ch=text[index]
        if quoted:
            if escaped:escaped=False
            elif ch=="\\":escaped=True
            elif ch=='"':quoted=False
            continue
        if ch=='"':quoted=True;continue
        if ch=="(":depth+=1
        elif ch==")":
            depth-=1
            if depth==0:return start,index
    raise ValueError("Unreal OptionSettings entry is malformed")

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

def _property_line(existing:str,key:str,value:str,syntax:str)->str:
    body,comment=_comment_parts(existing);comment_suffix=(" " if comment and body and not body.endswith((" ","\t")) else "")+comment
    if syntax=="semicolon":
        match=re.match(rf'^(\s*{re.escape(key)}\s*=\s*)(.*?)(\s*;\s*)$',body)
        if match:return match.group(1)+value+match.group(3)+comment_suffix
    elif syntax=="equals":
        match=re.match(rf'^(\s*{re.escape(key)}\s*=\s*)(.*?)\s*$',body)
        if match:return match.group(1)+value+(" " if comment else "")+comment
    return f"{key} = {value};" if syntax=="semicolon" else f"{key}={value}"

def _set_property(text:str,key:str,value:str,syntax:str)->str:
    if syntax=="ue_option_settings":
        start,end=_ue_bounds(text);body=text[start:end]
        pattern=re.compile(rf"(?<![A-Za-z0-9_]){re.escape(key)}\s*=\s*(?:\"(?:\\.|[^\"])*\"|[^,)]*)")
        replacement=f"{key}={value}"
        body=pattern.sub(replacement,body,count=1) if pattern.search(body) else (body.rstrip()+("," if body.strip() else "")+replacement)
        return text[:start]+body+text[end:]
    if syntax=="command":
        pattern=re.compile(rf"(?m)^\s*{re.escape(key)}\s+.*$");line=f"{key} {value}"
        if pattern.search(text):return pattern.sub(line,text,count=1)
        return text.rstrip("\n")+("\n" if text else "")+line+"\n"
    line=f"{key} = {value};" if syntax=="semicolon" else f"{key}={value}"
    property_pattern=re.compile(rf"^\s*{re.escape(key)}\s*=")
    lines=text.splitlines();updated=[];found=False
    for existing in lines:
        if property_pattern.match(existing):
            if not found:
                updated.append(_property_line(existing,key,value,syntax));found=True
            continue
        updated.append(existing)
    if found:
        result="\n".join(updated)
        if text.endswith(("\n","\r")):result+="\n"
        return result
    return text.rstrip("\n")+("\n" if text else "")+line+"\n"

def _apply_property(target:Path,binding:dict[str,Any],value:Any)->None:
    text=target.read_text(encoding="utf-8",errors="replace") if target.exists() else ""
    rendered=_binding_value(binding,value);updated=_set_property(text,str(binding["key"]),rendered,str(binding.get("syntax") or "equals"))
    _atomic_text(target,updated)

def _apply_json(target:Path,binding:dict[str,Any],value:Any)->None:
    if target.exists():
        try:payload=json.loads(target.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError) as exc:raise ValueError("invalid JSON server settings target") from exc
        if not isinstance(payload,dict):raise ValueError("JSON server settings target must be an object")
    else:payload={}
    keys=list(binding.get("keys") or []);cursor=payload
    for key in keys[:-1]:
        name=str(key);child=cursor.get(name)
        if child is None:child={};cursor[name]=child
        if not isinstance(child,dict):raise ValueError("JSON server settings path collides with a scalar")
        cursor=child
    cursor[str(keys[-1])]=value
    _atomic_text(target,json.dumps(payload,indent=2,sort_keys=True,ensure_ascii=False)+"\n")

def _apply_xml(target:Path,binding:dict[str,Any],value:Any)->None:
    if not target.is_file():raise ValueError("XML server settings target is unavailable")
    try:tree=ET.parse(target)
    except ET.ParseError as exc:raise ValueError("invalid XML server settings target") from exc
    root=tree.getroot();key=str(binding["key"]);node=None
    for item in root.findall(".//property"):
        if str(item.attrib.get("name") or "")==key:node=item;break
    if node is None:node=ET.SubElement(root,"property");node.set("name",key)
    node.set("value",_binding_value(binding,value))
    data=ET.tostring(root,encoding="unicode")
    _atomic_text(target,'<?xml version="1.0" encoding="utf-8"?>\n'+data+'\n')

def _apply_ini(target:Path,binding:dict[str,Any],value:Any)->None:
    section=str(binding["section"]);key=str(binding["key"]);rendered=_binding_value(binding,value)
    lines=target.read_text(encoding="utf-8",errors="replace").splitlines() if target.exists() else []
    start=None;end=len(lines)
    for i,line in enumerate(lines):
        stripped=line.strip()
        if stripped.lower()==f"[{section}]".lower():start=i;continue
        if start is not None and i>start and stripped.startswith("[") and stripped.endswith("]"):end=i;break
    if start is None:
        if lines and lines[-1].strip():lines.append("")
        lines.extend([f"[{section}]",f"{key}={rendered}"])
    else:
        pattern=re.compile(rf"^\s*{re.escape(key)}\s*=",re.I);found=False
        for i in range(start+1,end):
            if pattern.search(lines[i]):lines[i]=f"{key}={rendered}";found=True;break
        if not found:lines.insert(end,f"{key}={rendered}")
    _atomic_text(target,"\n".join(lines)+"\n")

def _apply_argument(args:list[str],binding:dict[str,Any],value:Any)->list[str]:
    result=list(args);flag=str(binding["flag"]);rendered=_binding_value(binding,value);style=str(binding.get("style") or "pair")
    if style=="equals":
        prefix=flag+"="
        for i,item in enumerate(result):
            if str(item).lower().startswith(prefix.lower()):result[i]=prefix+rendered;return result
        result.append(prefix+rendered);return result
    for i,item in enumerate(result):
        if str(item).lower()==flag.lower():
            if i+1<len(result):result[i+1]=rendered
            else:result.append(rendered)
            return result
    result.extend([flag,rendered]);return result

def _apply_launch_option(args:list[str],binding:dict[str,Any],value:Any)->list[str]:
    result=list(args);index=int(binding.get("argument_index",0))
    if index>=len(result):raise ValueError("launch option argument is unavailable")
    raw=str(result[index]);parts=raw.split("?");base=parts[0];options=parts[1:];key=str(binding["key"]);rendered=_binding_value(binding,value);found=False
    for i,item in enumerate(options):
        name,sep,_old=item.partition("=")
        if sep and name.lower()==key.lower():options[i]=f"{name}={rendered}";found=True;break
    if not found:options.append(f"{key}={rendered}")
    result[index]="?".join([base,*options]);return result

def _apply_command_batch(args:list[str],binding:dict[str,Any],value:Any)->list[str]:
    result=list(args);index=int(binding.get("argument_index",2))
    if index>=len(result):raise ValueError("command batch argument is unavailable")
    separator=str(binding.get("separator") or ",");command=str(binding.get("command") or "").strip();before=str(binding.get("before") or "host").strip();rendered=_binding_value(binding,value)
    parts=[item.strip() for item in str(result[index]).split(separator) if item.strip()];replacement=f"{command} {rendered}";found=False
    for i,item in enumerate(parts):
        if item.lower()==command.lower() or item.lower().startswith(command.lower()+" "):
            parts[i]=replacement;found=True;break
    if not found:
        position=next((i for i,item in enumerate(parts) if item.lower()==before.lower()),len(parts));parts.insert(position,replacement)
    result[index]=separator.join(parts);return result

def prepare_spec(spec:dict[str,Any],values:dict[str,Any],*,declaration:dict[str,Any]|None=None)->dict[str,Any]:
    if not isinstance(spec,dict) or not isinstance(values,dict):raise ValueError("invalid server settings application")
    local=spec.get("catalog_server_settings") if isinstance(spec.get("catalog_server_settings"),dict) else {}
    declaration=local if isinstance(local.get("fields"),dict) and local.get("fields") else (declaration if isinstance(declaration,dict) else {})
    fields=declaration.get("fields") if isinstance(declaration.get("fields"),dict) else {}
    unknown=set(values)-set(fields)
    if unknown:raise ValueError("undeclared server settings: "+", ".join(sorted(unknown)))
    normalized={key:_coerce(key,fields[key],value) for key,value in values.items()}
    result=dict(spec);result["catalog_server_settings"]=dict(declaration);base=result.get("server_settings_base_arguments")
    if not isinstance(base,list):base=list(result.get("arguments") or [])
    args=list(base);has_argument=False
    for key,value in normalized.items():
        binding=fields[key].get("binding") if isinstance(fields[key].get("binding"),dict) else {}
        kind=str(binding.get("kind") or "")
        if kind=="argument":args=_apply_argument(args,binding,value);has_argument=True
        elif kind=="launch_option":args=_apply_launch_option(args,binding,value);has_argument=True
        elif kind=="command_batch":args=_apply_command_batch(args,binding,value);has_argument=True
        elif kind in _FILE_KINDS:
            activation=binding.get("activate_argument") if isinstance(binding.get("activate_argument"),dict) else None
            if activation:
                root=Path(str(result.get("configuration_root") or "")).resolve(strict=False);target=(root/Path(str(binding.get("path") or ""))).resolve(strict=False);target.relative_to(root);args=_apply_argument(args,activation,str(target));has_argument=True
        else:raise ValueError(f"unsupported server settings binding: {key}")
    if has_argument:
        result["server_settings_base_arguments"]=list(base);result["arguments"]=args
    result["server_settings_values"]=normalized
    return result

def materialize_server_settings(spec:dict[str,Any])->list[str]:
    values=spec.get("server_settings_values") if isinstance(spec.get("server_settings_values"),dict) else {}
    if not values:return []
    declaration=spec.get("catalog_server_settings") if isinstance(spec.get("catalog_server_settings"),dict) else {};fields=declaration.get("fields") if isinstance(declaration.get("fields"),dict) else {}
    root=_root(spec);written=[]
    for key,value in values.items():
        field=fields.get(key)
        if not isinstance(field,dict):raise ValueError(f"server setting declaration disappeared: {key}")
        binding=field.get("binding") if isinstance(field.get("binding"),dict) else {};kind=str(binding.get("kind") or "")
        if kind in _ARG_KINDS:continue
        target=_target(root,str(binding.get("path") or ""))
        if kind=="property":_apply_property(target,binding,value)
        elif kind=="json":_apply_json(target,binding,value)
        elif kind=="xml_property":_apply_xml(target,binding,value)
        elif kind=="ini":_apply_ini(target,binding,value)
        else:raise ValueError(f"unsupported server settings binding: {key}")
        written.append(str(target.relative_to(root)).replace("\\","/"))
    return sorted(set(written))

__all__=["materialize_server_settings","prepare_spec"]
