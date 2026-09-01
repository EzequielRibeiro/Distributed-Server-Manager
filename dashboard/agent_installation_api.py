#!/usr/bin/env python3
"""Agent installation planning, remote bootstrap and progress tracking."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from agent_install_command import linux_agent_install_command
from windows_agent_install_command import windows_agent_install_command
from agent_pairing_repository import AgentPairingRepository
from agent_installation_preconfiguration import AgentInstallationPreconfigurationRepository, normalize_preconfiguration
from agent_release_service import resolve_agent_release
from alert_repository import AlertSession, dialect_for_backend
from infrastructure_repository import InfrastructureRepository
from core.agent_ssh_deploy import (
    AgentDeployError, SSHDeployOptions, bootstrap_agent, bootstrap_agent_package,
    bootstrap_windows_agent_ssh, preflight_ssh, preflight_windows_ssh,
    remote_agent_present, remote_windows_agent_present_ssh,
)
from core.agent_winrm_deploy import (
    WinRMDeployError, bootstrap_windows_agent, load_winrm_profile, preflight_winrm,
    remote_windows_agent_present,
)

def _role(user: dict[str, Any] | None) -> str:
    if not user: raise PermissionError("authentication required")
    return str(user.get("role", "")).strip().lower()

def _controller_scope(user: dict[str, Any], requested: str | None) -> str:
    role=_role(user); requested_id=str(requested or "").strip()
    if role=="admin":
        if not requested_id: raise ValueError("controller_id is required")
        return requested_id
    if role=="controller":
        scope_id=str(user.get("scope_id","")).strip()
        if not scope_id: raise PermissionError("controller scope is required")
        if requested_id and requested_id!=scope_id: raise PermissionError("controller is outside user scope")
        return scope_id
    raise PermissionError("Agent installation is not permitted")

def _location(backend, region_id: str, datacenter_id: str) -> tuple[dict[str,Any],dict[str,Any]]:
    infrastructure=InfrastructureRepository(backend)
    regions=infrastructure.regions(active_only=True); datacenters=infrastructure.datacenters(region_id=region_id,active_only=True)
    region=next((x for x in regions if str(x["id"])==region_id),None)
    datacenter=next((x for x in datacenters if str(x["id"])==datacenter_id),None)
    if region is None: raise ValueError("region not found or inactive")
    if datacenter is None: raise ValueError("datacenter not found in selected region or inactive")
    return region,datacenter

def _local_instruction(platform: str, controller_url: str, pairing_token: str) -> str:
    if platform=="windows":
        return ".\\install-agent.ps1 -ControllerUrl '"+controller_url.replace("'","''")+"' -PairingToken '"+pairing_token.replace("'","''")+"'"
    return "sudo ./install-agent.sh --controller-url "+controller_url+" --pairing-token "+pairing_token

def _dashboard_password_file(raw: Any) -> str | None:
    value=str(raw or "").strip()
    if not value: return None
    root=Path(os.environ.get("DSM_REMOTE_DEPLOY_SECRET_DIR","/etc/capivara/secrets/remote-deploy")).resolve()
    path=Path(value).expanduser().resolve()
    try: path.relative_to(root)
    except ValueError as exc: raise ValueError(f"password_file must be inside {root}") from exc
    return str(path)

def _dashboard_agent_package_file(raw: Any) -> str | None:
    value=str(raw or "").strip()
    if not value: return None
    root=Path(os.environ.get("DSM_AGENT_LOCAL_PACKAGE_DIR","/var/lib/capivara/agent-packages")).resolve()
    path=Path(value).expanduser().resolve()
    try: path.relative_to(root)
    except ValueError as exc: raise ValueError(f"package_file must be inside {root}") from exc
    if not path.is_file(): raise ValueError(f"local Agent package not found: {path}")
    return str(path)

def _ssh_options(payload: dict[str,Any]) -> SSHDeployOptions:
    if payload.get("password") not in (None,"") or payload.get("ssh_password") not in (None,""):
        raise ValueError("SSH passwords are never accepted directly; use a protected password_file")
    if payload.get("identity_file") not in (None,""):
        raise ValueError("identity_file paths are not accepted from the Dashboard; configure the Controller SSH identity")
    host=str(payload.get("ssh_host","") or "").strip(); user=str(payload.get("ssh_user","") or "").strip()
    if not host: raise ValueError("ssh_host is required for remote installation")
    if not user: raise ValueError("ssh_user is required for remote installation")
    try: port=int(payload.get("ssh_port",22) or 22)
    except (TypeError,ValueError) as exc: raise ValueError("ssh_port must be an integer") from exc
    return SSHDeployOptions(host=host,ssh_user=user,ssh_port=port,password_file=_dashboard_password_file(payload.get("password_file")))

def _bootstrap_timeout(payload: dict[str,Any]) -> int:
    try: timeout=int(payload.get("bootstrap_timeout",900) or 900)
    except (TypeError,ValueError) as exc: raise ValueError("bootstrap_timeout must be an integer") from exc
    if timeout<30 or timeout>3600: raise ValueError("bootstrap_timeout must be between 30 and 3600 seconds")
    return timeout

def _expire_installation_token(backend, installation_id: str) -> None:
    dialect=dialect_for_backend(backend); ph=dialect.placeholder; now=dialect.current_timestamp
    with backend.transaction() as connection:
        session=AlertSession(backend,connection)
        try: session.execute("UPDATE agent_pairing_tokens SET expires_at="+now+" WHERE id="+ph+" AND consumed_at IS NULL",(str(installation_id),))
        finally: session.close()

def _run_ssh_preflight(platform: str, options: SSHDeployOptions, ssh_runner=None) -> dict[str,Any]:
    try:
        if platform=="windows":
            result=preflight_windows_ssh(options) if ssh_runner is None else preflight_windows_ssh(options,runner=ssh_runner)
            present=remote_windows_agent_present_ssh(options) if ssh_runner is None else remote_windows_agent_present_ssh(options,runner=ssh_runner)
        else:
            result=preflight_ssh(options) if ssh_runner is None else preflight_ssh(options,runner=ssh_runner)
            present=remote_agent_present(options) if ssh_runner is None else remote_agent_present(options,runner=ssh_runner)
    except AgentDeployError as exc: raise ValueError(str(exc)) from exc
    if present: raise ValueError("Capivara Agent already detected on remote host; automatic reinstall was refused")
    return result

def _run_ssh_bootstrap(platform: str, options: SSHDeployOptions, *, controller_url: str,pairing_token: str,release_tag: str,timeout: int,ssh_runner=None,package_file: str|None=None) -> None:
    try:
        if package_file:
            if platform!="linux": raise ValueError("local package batch installation is currently supported for Linux Agents only")
            kwargs={"controller_url":controller_url,"pairing_token":pairing_token,"package_file":package_file,"timeout":timeout}
            if ssh_runner is None: bootstrap_agent_package(options,**kwargs)
            else: bootstrap_agent_package(options,runner=ssh_runner,transfer_runner=ssh_runner,**kwargs)
            return
        kwargs={"controller_url":controller_url,"pairing_token":pairing_token,"release_tag":release_tag,"timeout":timeout}
        fn=bootstrap_windows_agent_ssh if platform=="windows" else bootstrap_agent
        if ssh_runner is None: fn(options,**kwargs)
        else: fn(options,runner=ssh_runner,**kwargs)
    except AgentDeployError as exc: raise ValueError(str(exc)) from exc

def create_agent_installation_for_user(user: dict[str,Any]|None, backend, payload: dict[str,Any]|None, *, ssh_runner=None, winrm_runner=None) -> dict[str,Any]:
    if not isinstance(payload,dict): raise ValueError("payload must be an object")
    controller_id=_controller_scope(user or {},payload.get("controller_id")); platform=str(payload.get("platform","linux")).strip().lower(); method=str(payload.get("method","github")).strip().lower()
    region_id=str(payload.get("region_id","")).strip(); datacenter_id=str(payload.get("datacenter_id","")).strip(); controller_url=str(payload.get("controller_url","")).strip().rstrip("/")
    if platform not in {"linux","windows"}: raise ValueError("unsupported Agent platform")
    if method not in {"github","local","ssh","winrm"}: raise ValueError("unsupported installation method")
    if method=="winrm" and platform!="windows": raise ValueError("remote WinRM installation supports Windows Agents only")
    if not controller_url.startswith(("http://","https://")): raise ValueError("controller_url must use http:// or https://")
    package_file=_dashboard_agent_package_file(payload.get("package_file")) if method=="ssh" else None
    if payload.get("package_file") not in (None,"") and method!="ssh": raise ValueError("package_file is supported only with SSH batch installation")
    if package_file and platform!="linux": raise ValueError("local package batch installation is currently supported for Linux Agents only")
    release=None; release_tag="local-package" if package_file else "local"
    if method in {"github","ssh","winrm"} and not package_file:
        requested=str(payload.get("release_tag") or "").strip()
        if requested: release=resolve_agent_release(requested,platform); release_tag=str(release["tag"])
        else: release_tag="latest"
    preconfiguration=normalize_preconfiguration(payload); region,datacenter=_location(backend,region_id,datacenter_id)
    ssh_options=None; ssh_preflight=None; bootstrap_timeout=None
    if method=="ssh":
        ssh_options=_ssh_options(payload); bootstrap_timeout=_bootstrap_timeout(payload); ssh_preflight=_run_ssh_preflight(platform,ssh_options,ssh_runner=ssh_runner)
    winrm_options=None; winrm_preflight=None
    if method=="winrm":
        host=str(payload.get("winrm_host","") or "").strip()
        if not host: raise ValueError("winrm_host is required for remote installation")
        if payload.get("password") not in (None,"") or payload.get("winrm_password") not in (None,""): raise ValueError("Windows passwords are not accepted by the Dashboard")
        try:
            winrm_options=load_winrm_profile(host); winrm_preflight=preflight_winrm(winrm_options,runner=winrm_runner)
            if remote_windows_agent_present(winrm_options,runner=winrm_runner): raise ValueError("Capivara Agent already detected on Windows host; automatic reinstall was refused")
        except WinRMDeployError as exc: raise ValueError(str(exc)) from exc
    issued=AgentPairingRepository(backend).issue_token(controller_id=controller_id,created_by=str((user or {}).get("username","")).strip() or None,ttl_seconds=int(payload.get("ttl_seconds",900) or 900))
    dialect=dialect_for_backend(backend); ph=dialect.placeholder
    with backend.transaction() as connection:
        session=AlertSession(backend,connection)
        try: session.execute("UPDATE agent_pairing_tokens SET platform="+ph+",install_method="+ph+",region_id="+ph+",datacenter_id="+ph+" WHERE id="+ph,(platform,method,region_id,datacenter_id,issued.token_id))
        finally: session.close()
    AgentInstallationPreconfigurationRepository(backend).save(issued.token_id,preconfiguration)
    instruction=None; remote_bootstrap=None
    if method=="github":
        instruction=windows_agent_install_command(controller_url=controller_url,pairing_token=issued.token,release_tag=release_tag) if platform=="windows" else linux_agent_install_command(controller_url=controller_url,pairing_token=issued.token,release_tag=release_tag)
    elif method=="local": instruction=_local_instruction(platform,controller_url,issued.token)
    elif method=="ssh":
        assert ssh_options is not None and bootstrap_timeout is not None
        try: _run_ssh_bootstrap(platform,ssh_options,controller_url=controller_url,pairing_token=issued.token,release_tag=release_tag,timeout=bootstrap_timeout,ssh_runner=ssh_runner,package_file=package_file)
        except Exception: _expire_installation_token(backend,issued.token_id); raise
        remote_bootstrap={"state":"completed","host":ssh_options.host,"ssh_user":ssh_options.ssh_user,"ssh_port":ssh_options.ssh_port,"transport":"openssh-local-package" if package_file else "openssh","platform":ssh_preflight.get("platform") if ssh_preflight else platform,"architecture":ssh_preflight.get("architecture") if ssh_preflight else None,"release_tag":release_tag,"package_file":Path(package_file).name if package_file else None}
    else:
        assert winrm_options is not None
        try: bootstrap_windows_agent(winrm_options,controller_url=controller_url,pairing_token=issued.token,release_tag=release_tag,runner=winrm_runner)
        except Exception: _expire_installation_token(backend,issued.token_id); raise
        remote_bootstrap={"state":"completed","host":winrm_options.host,"winrm_port":winrm_options.port,"transport":"winrm-https-certificate","platform":"windows","architecture":winrm_preflight.get("architecture") if winrm_preflight else None,"release_tag":release_tag}
    return {"installation_id":issued.token_id,"controller_id":controller_id,"platform":platform,"method":method,"release_tag":release_tag,"release":release,"region":{"id":region["id"],"name":region["name"]},"datacenter":{"id":datacenter["id"],"name":datacenter["name"]},"expires_at":issued.expires_at,"instruction":instruction,"remote_bootstrap":remote_bootstrap,"preconfiguration":preconfiguration,"state":"waiting","state_label":"Aguardando Agent"}

def agent_installation_status_for_user(user: dict[str,Any]|None, backend, installation_id: str) -> dict[str,Any]:
    installation_id=str(installation_id).strip()
    if not installation_id: raise ValueError("installation_id is required")
    dialect=dialect_for_backend(backend); ph=dialect.placeholder
    with backend.connect() as connection:
        session=AlertSession(backend,connection)
        try:
            row=session.execute("SELECT controller_id,platform,install_method,region_id,datacenter_id,agent_id,consumed_at,expires_at FROM agent_pairing_tokens WHERE id="+ph,(installation_id,)).fetchone()
            if row is None: raise LookupError("installation not found")
            _controller_scope(user or {},str(row["controller_id"])); agent=None; inventory=None
            if row["agent_id"]:
                agent=session.execute("SELECT id,status FROM agents WHERE id="+ph,(str(row["agent_id"]),)).fetchone()
                inventory=session.execute("SELECT health_status,last_seen FROM agent_runtime_inventory WHERE agent_id="+ph,(str(row["agent_id"]),)).fetchone()
        finally: session.close()
    preconfiguration=AgentInstallationPreconfigurationRepository(backend).get(installation_id); state="waiting"; label="Aguardando Agent"
    if row["consumed_at"]: state,label="pairing","Pareando"
    if agent is not None and str(agent["status"]).lower()=="active": state,label="validating","Validando"
    if inventory is not None and str(inventory["health_status"] or "").lower()=="online": state,label="online","Online"
    return {"installation_id":installation_id,"agent_id":str(row["agent_id"]) if row["agent_id"] else None,"platform":str(row["platform"]) if row["platform"] else None,"method":str(row["install_method"]) if row["install_method"] else None,"state":state,"state_label":label,"agent_status":str(agent["status"]) if agent is not None else None,"health_status":str(inventory["health_status"]) if inventory is not None else None,"last_seen":inventory["last_seen"] if inventory is not None else None,"expires_at":row["expires_at"],"preconfiguration":preconfiguration}

def bind_installation_after_enrollment(backend, *, pairing_token: str, agent_id: str) -> None:
    from core.agent_identity import secret_digest
    from location_repository import LocationRepository
    dialect=dialect_for_backend(backend); ph=dialect.placeholder; token_hash=secret_digest(pairing_token)
    with backend.transaction() as connection:
        session=AlertSession(backend,connection)
        try:
            row=session.execute("SELECT id,datacenter_id FROM agent_pairing_tokens WHERE token_hash="+ph,(token_hash,)).fetchone()
            if row is None: return
            session.execute("UPDATE agent_pairing_tokens SET agent_id="+ph+" WHERE id="+ph,(agent_id,str(row["id"])))
        finally: session.close()
    if row["datacenter_id"]: LocationRepository(backend).upsert_agent_location(agent_id=agent_id,datacenter_id=str(row["datacenter_id"]),status="active")
    try: AgentInstallationPreconfigurationRepository(backend).apply(str(row["id"]),agent_id)
    except Exception: pass
