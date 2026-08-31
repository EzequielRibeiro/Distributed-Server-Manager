#!/usr/bin/env python3
"""Non-destructive remote Agent connectivity checks for the Dashboard."""
from __future__ import annotations
import os
import shlex
from pathlib import Path
from typing import Any
from core.agent_ssh_deploy import (
    AgentDeployError,
    SSHDeployOptions,
    _powershell_encoded_command,
    _run_ssh,
    preflight_ssh,
    preflight_windows_ssh,
)

_CONTROLLER_OK = "CAPIVARA_CONTROLLER_REACHABLE_OK"


def _authorized(user: dict[str, Any] | None) -> None:
    role=str((user or {}).get("role","")).strip().lower()
    if role not in {"admin","controller"}: raise PermissionError("Agent connection test is not permitted")


def _password_file(raw: Any) -> str | None:
    value=str(raw or "").strip()
    if not value: return None
    root=Path(os.environ.get("DSM_REMOTE_DEPLOY_SECRET_DIR","/etc/capivara/secrets/remote-deploy")).resolve()
    path=Path(value).expanduser().resolve()
    try: path.relative_to(root)
    except ValueError as exc: raise ValueError(f"password_file must be inside {root}") from exc
    return str(path)


def _controller_url(raw: Any) -> str:
    value=str(raw or "").strip().rstrip("/")
    if not value: raise ValueError("controller_url is required for remote installation")
    if not value.startswith(("http://","https://")):
        raise ValueError("controller_url must use http:// or https://")
    return value


def _controller_probe_command(platform: str, controller_url: str) -> str:
    target=controller_url.rstrip("/")+"/agent/install.ps1"
    if platform=="windows":
        escaped=target.replace("'","''")
        script=(
            "$ErrorActionPreference='Stop';"
            "$ProgressPreference='SilentlyContinue';"
            f"$r=Invoke-WebRequest -UseBasicParsing -Uri '{escaped}';"
            f"if($r.StatusCode -ge 200 -and $r.StatusCode -lt 400){{Write-Output '{_CONTROLLER_OK}';exit 0}}else{{exit 1}}"
        )
        return _powershell_encoded_command(script)
    code=(
        "import ssl,urllib.request;"
        f"u={target!r};"
        "r=urllib.request.urlopen(u,timeout=10,context=ssl.create_default_context());"
        "s=getattr(r,'status',200);"
        f"print('{_CONTROLLER_OK}' if 200<=s<400 else 'FAIL');"
        "raise SystemExit(0 if 200<=s<400 else 1)"
    )
    return "python3 -c "+shlex.quote(code)


def _check_controller_reachable(platform: str, options: SSHDeployOptions, controller_url: str, *, ssh_runner=None) -> None:
    result=_run_ssh(
        options,
        _controller_probe_command(platform,controller_url),
        runner=ssh_runner if ssh_runner is not None else None,
        timeout=options.connect_timeout+15,
    ) if ssh_runner is not None else _run_ssh(
        options,
        _controller_probe_command(platform,controller_url),
        timeout=options.connect_timeout+15,
    )
    if result.returncode!=0 or _CONTROLLER_OK not in result.stdout:
        detail=(result.stderr or result.stdout or "remote host could not reach the Controller URL with valid TLS").strip()
        raise ValueError("Controller URL is not reachable from the Agent host: "+detail)


def test_agent_connection_for_user(user: dict[str,Any]|None,payload: dict[str,Any]|None,*,ssh_runner=None) -> dict[str,Any]:
    _authorized(user)
    if not isinstance(payload,dict): raise ValueError("payload must be an object")
    if payload.get("password") not in (None,"") or payload.get("ssh_password") not in (None,""):
        raise ValueError("SSH passwords are never accepted directly; use password_file")
    platform=str(payload.get("platform","linux")).strip().lower()
    if platform not in {"linux","windows"}: raise ValueError("unsupported Agent platform")
    host=str(payload.get("ssh_host","") or "").strip(); ssh_user=str(payload.get("ssh_user","") or "").strip()
    if not host: raise ValueError("ssh_host is required")
    if not ssh_user: raise ValueError("ssh_user is required")
    controller_url=_controller_url(payload.get("controller_url"))
    try: port=int(payload.get("ssh_port",22) or 22)
    except (TypeError,ValueError) as exc: raise ValueError("ssh_port must be an integer") from exc
    options=SSHDeployOptions(host=host,ssh_user=ssh_user,ssh_port=port,password_file=_password_file(payload.get("password_file")))
    try:
        fn=preflight_windows_ssh if platform=="windows" else preflight_ssh
        result=fn(options) if ssh_runner is None else fn(options,runner=ssh_runner)
    except AgentDeployError as exc: raise ValueError(str(exc)) from exc
    _check_controller_reachable(platform,options,controller_url,ssh_runner=ssh_runner)
    return {"ok":True,"host":host,"ssh_user":ssh_user,"ssh_port":port,"platform":result.get("platform",platform),"architecture":result.get("architecture"),"transport":"openssh","authentication":"password-file" if options.password_file else "ssh-key-or-agent","controller_url":controller_url,"controller_reachable":True}
