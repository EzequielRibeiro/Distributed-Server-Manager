#!/usr/bin/env python3
"""Remote Agent bootstrap over OpenSSH.

SSH is used only for first-install bootstrap. Linux and Windows share the
transport, while keeping platform-specific preflight and bootstrap commands.
"""
from __future__ import annotations
import ipaddress, json, os, re, shutil, stat, subprocess, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

class AgentDeployError(RuntimeError): pass

@dataclass(frozen=True)
class SSHDeployOptions:
    host: str
    ssh_user: str
    ssh_port: int = 22
    identity_file: str | None = None
    password_file: str | None = None
    connect_timeout: int = 10

@dataclass(frozen=True)
class SSHResult:
    returncode: int
    stdout: str
    stderr: str

SSHRunner = Callable[[Sequence[str], str | None, int | None], SSHResult]
_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

def validate_host(value: str) -> str:
    host = str(value or "").strip()
    if not host or not _HOST_RE.fullmatch(host): raise AgentDeployError("invalid SSH host")
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try: ipaddress.ip_address(candidate)
    except ValueError:
        labels = candidate.rstrip(".").split(".")
        if any(not x or len(x)>63 or x.startswith("-") or x.endswith("-") for x in labels):
            raise AgentDeployError("invalid SSH host")
    return candidate

def validate_ssh_user(value: str) -> str:
    user = str(value or "").strip()
    if not _USER_RE.fullmatch(user): raise AgentDeployError("invalid SSH user")
    return user

def validate_password_file(value: str) -> Path:
    path = Path(os.path.expanduser(str(value or ""))).resolve()
    if not path.is_file(): raise AgentDeployError(f"SSH password file not found: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise AgentDeployError(f"SSH password file has unsafe permissions {mode:04o}; use 0600 or more restrictive")
    try: secret = path.read_text(encoding="utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc: raise AgentDeployError("SSH password file must be UTF-8 text") from exc
    if not secret: raise AgentDeployError("SSH password file is empty")
    return path

def _default_runner(argv: Sequence[str], stdin_text: str | None, timeout: int | None) -> SSHResult:
    p=subprocess.run(list(argv),input=stdin_text,text=True,capture_output=True,timeout=timeout,check=False)
    return SSHResult(p.returncode,p.stdout,p.stderr)

def build_ssh_argv(options: SSHDeployOptions, remote_command: str) -> list[str]:
    host,user=validate_host(options.host),validate_ssh_user(options.ssh_user)
    if not 1<=int(options.ssh_port)<=65535: raise AgentDeployError("ssh_port must be between 1 and 65535")
    if not 1<=int(options.connect_timeout)<=300: raise AgentDeployError("connect_timeout must be between 1 and 300 seconds")
    if options.identity_file and options.password_file: raise AgentDeployError("use either identity_file or password_file, not both")
    password_path=validate_password_file(options.password_file) if options.password_file else None
    argv=[]
    if password_path: argv.extend(["sshpass","-f",str(password_path)])
    argv.extend(["ssh","-p",str(int(options.ssh_port)),"-o",f"ConnectTimeout={int(options.connect_timeout)}","-o","BatchMode=no" if password_path else "BatchMode=yes"])
    if password_path: argv.extend(["-o","PreferredAuthentications=password,keyboard-interactive"])
    if options.identity_file:
        identity=Path(os.path.expanduser(str(options.identity_file))).resolve()
        if not identity.is_file(): raise AgentDeployError(f"SSH identity file not found: {identity}")
        argv.extend(["-i",str(identity)])
    argv.extend([f"{user}@{host}",remote_command])
    return argv

def _run_ssh(options: SSHDeployOptions, remote_command: str, *, runner: SSHRunner, stdin_text: str|None=None, timeout: int|None=None) -> SSHResult:
    if runner is _default_runner:
        if shutil.which("ssh") is None: raise AgentDeployError("OpenSSH client not found")
        if options.password_file and shutil.which("sshpass") is None:
            raise AgentDeployError("password-file authentication requires sshpass on the Controller; SSH keys remain preferred")
    try: return runner(build_ssh_argv(options,remote_command),stdin_text,timeout)
    except subprocess.TimeoutExpired as exc: raise AgentDeployError("SSH operation timed out") from exc
    except OSError as exc: raise AgentDeployError(f"unable to execute SSH client: {exc}") from exc

def _reason(result: SSHResult, fallback: str) -> str:
    lines=(result.stderr or result.stdout).strip().splitlines(); return lines[-1] if lines else fallback

def preflight_ssh(options: SSHDeployOptions, *, runner: SSHRunner=_default_runner) -> dict[str,Any]:
    cmd='set -eu; test "$(uname -s)" = Linux; command -v bash >/dev/null; command -v curl >/dev/null; command -v python3 >/dev/null; if [ "$(id -u)" -ne 0 ]; then command -v sudo >/dev/null; sudo -n true; fi; printf "CAPIVARA_PREFLIGHT_OK\\n"; uname -m'
    r=_run_ssh(options,cmd,runner=runner,timeout=options.connect_timeout+10)
    if r.returncode!=0 or "CAPIVARA_PREFLIGHT_OK" not in r.stdout:
        raise AgentDeployError("SSH preflight failed (Linux, curl, bash, python3 and root/passwordless sudo are required): "+_reason(r,"remote preflight failed"))
    lines=[x.strip() for x in r.stdout.splitlines() if x.strip()]
    return {"platform":"linux","architecture":lines[-1] if lines else "unknown","transport":"openssh"}

def preflight_windows_ssh(options: SSHDeployOptions, *, runner: SSHRunner=_default_runner) -> dict[str,Any]:
    ps="$ErrorActionPreference='Stop';$id=[Security.Principal.WindowsIdentity]::GetCurrent();$p=New-Object Security.Principal.WindowsPrincipal($id);if(-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 41};Write-Output 'CAPIVARA_WINDOWS_PREFLIGHT_OK';Write-Output $env:PROCESSOR_ARCHITECTURE"
    r=_run_ssh(options,'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "'+ps+'"',runner=runner,timeout=options.connect_timeout+15)
    if r.returncode!=0 or "CAPIVARA_WINDOWS_PREFLIGHT_OK" not in r.stdout:
        raise AgentDeployError("SSH preflight failed (Windows OpenSSH, PowerShell and an Administrator account are required): "+_reason(r,"remote Windows preflight failed"))
    lines=[x.strip() for x in r.stdout.splitlines() if x.strip()]
    return {"platform":"windows","architecture":lines[-1] if lines else "unknown","transport":"openssh"}

def remote_agent_present(options: SSHDeployOptions, *, runner: SSHRunner=_default_runner) -> bool:
    return _run_ssh(options,"test -f /var/lib/capivara-agent/identity.json -o -f /etc/capivara-agent/agent.conf",runner=runner,timeout=options.connect_timeout+5).returncode==0

def remote_windows_agent_present_ssh(options: SSHDeployOptions, *, runner: SSHRunner=_default_runner) -> bool:
    ps="$p=@('C:\\ProgramData\\Capivara\\Agent\\identity.json','C:\\ProgramData\\Capivara\\Agent\\agent.conf');if($p|Where-Object{Test-Path $_}){exit 0}else{exit 1}"
    return _run_ssh(options,'powershell.exe -NoProfile -NonInteractive -Command "'+ps+'"',runner=runner,timeout=options.connect_timeout+5).returncode==0

def _bootstrap_stdin(controller_url: str,pairing_token: str,release_tag: str="latest") -> str:
    payload=json.dumps({"controller_url":controller_url,"pairing_token":pairing_token,"release_tag":release_tag},separators=(",",":"))
    return f'''import json, os, subprocess, tempfile\npayload=json.loads({payload!r})\nurl=payload["controller_url"].rstrip("/")+"/agent/install.sh"\nfd,path=tempfile.mkstemp(prefix="capivara-agent-bootstrap-",suffix=".sh"); os.close(fd)\ntry:\n subprocess.run(["curl","-fsSL",url,"-o",path],check=True); os.chmod(path,0o700)\n env=os.environ.copy(); env["CAPIVARA_PAIRING_TOKEN"]=payload["pairing_token"]; env["CAPIVARA_RELEASE_TAG"]=payload["release_tag"]\n subprocess.run(["bash",path,"--controller-url",payload["controller_url"]],check=True,env=env)\nfinally:\n try: os.unlink(path)\n except FileNotFoundError: pass\n'''

def bootstrap_agent(options: SSHDeployOptions, *, controller_url: str,pairing_token: str,release_tag: str="latest",runner: SSHRunner=_default_runner,timeout: int=900) -> None:
    controller_url=str(controller_url or "").strip().rstrip("/"); pairing_token=str(pairing_token or "").strip(); release_tag=str(release_tag or "latest").strip()
    if not controller_url.startswith(("http://","https://")): raise AgentDeployError("controller_url must use http:// or https://")
    if not pairing_token: raise AgentDeployError("pairing token is required")
    cmd="python3 -" if validate_ssh_user(options.ssh_user)=="root" else "sudo -n python3 -"
    r=_run_ssh(options,cmd,runner=runner,stdin_text=_bootstrap_stdin(controller_url,pairing_token,release_tag),timeout=timeout)
    if r.returncode!=0: raise AgentDeployError("Agent bootstrap failed: "+_reason(r,"remote Agent bootstrap failed"))

def _windows_bootstrap_stdin(controller_url: str,pairing_token: str,release_tag: str) -> str:
    payload=json.dumps({"controller_url":controller_url,"pairing_token":pairing_token,"release_tag":release_tag}).replace("'","''")
    return f"$ErrorActionPreference='Stop'\n$payload=ConvertFrom-Json '{payload}'\n$url=$payload.controller_url.TrimEnd('/')+'/agent/install.ps1'\n$script=(Invoke-WebRequest -UseBasicParsing -Uri $url).Content\n& ([scriptblock]::Create($script)) -ControllerUrl $payload.controller_url -PairingToken $payload.pairing_token -ReleaseTag $payload.release_tag\n"

def bootstrap_windows_agent_ssh(options: SSHDeployOptions, *, controller_url: str,pairing_token: str,release_tag: str="latest",runner: SSHRunner=_default_runner,timeout: int=900) -> None:
    controller_url=str(controller_url or "").strip().rstrip("/"); pairing_token=str(pairing_token or "").strip(); release_tag=str(release_tag or "latest").strip()
    if not controller_url.startswith(("http://","https://")): raise AgentDeployError("controller_url must use http:// or https://")
    if not pairing_token: raise AgentDeployError("pairing token is required")
    r=_run_ssh(options,"powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command -",runner=runner,stdin_text=_windows_bootstrap_stdin(controller_url,pairing_token,release_tag),timeout=timeout)
    if r.returncode!=0: raise AgentDeployError("Windows Agent bootstrap failed: "+_reason(r,"remote Windows Agent bootstrap failed"))

def wait_for_agent_online(status_reader: Callable[[],dict[str,Any]], *, timeout: int=180,interval: float=2.0) -> dict[str,Any]:
    deadline=time.monotonic()+max(1,int(timeout)); latest={}
    while time.monotonic()<deadline:
        latest=dict(status_reader() or {})
        if str(latest.get("agent_status","")).lower()=="active" and str(latest.get("health_status","")).lower()=="online": return latest
        time.sleep(max(.05,float(interval)))
    raise AgentDeployError("Agent enrollment did not reach active/online before timeout"+(f" (last state: {latest})" if latest else ""))

__all__=["AgentDeployError","SSHDeployOptions","SSHResult","bootstrap_agent","bootstrap_windows_agent_ssh","build_ssh_argv","preflight_ssh","preflight_windows_ssh","remote_agent_present","remote_windows_agent_present_ssh","validate_host","validate_password_file","validate_ssh_user","wait_for_agent_online"]
