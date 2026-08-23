#!/usr/bin/env python3
"""Prepare passwordless, certificate-authenticated WinRM deployment."""
from __future__ import annotations
import argparse, base64, getpass, json, os, secrets, stat, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for candidate in (ROOT,ROOT/'core',ROOT/'database'):
    if str(candidate) not in sys.path:sys.path.insert(0,str(candidate))
from agent_winrm_deploy import PyWinRMRunner,WinRMDeployError,load_winrm_profile,preflight_winrm,profile_path,validate_winrm_host

def _split_target(value:str)->tuple[str,str]:
    if '@' not in str(value):raise WinRMDeployError('target must use USER@HOST')
    user,host=str(value).split('@',1)
    if not user.strip() or any(c in user for c in '\r\n`;$'):raise WinRMDeployError('invalid Windows administrator')
    return user.strip(),validate_winrm_host(host)

def _generate_certificate(host:str,directory:Path)->tuple[Path,Path]:
    directory.mkdir(parents=True,exist_ok=True,mode=0o700);key=directory/'client-key.pem';cert=directory/'client-cert.pem'
    command=['openssl','req','-x509','-newkey','rsa:3072','-nodes','-keyout',str(key),'-out',str(cert),'-days','825','-sha256','-subj',f"/CN=capivara-controller-{host.replace(':','-')}",'-addext','extendedKeyUsage=clientAuth']
    try:subprocess.run(command,check=True,capture_output=True,text=True,timeout=60)
    except (FileNotFoundError,subprocess.CalledProcessError) as exc:raise WinRMDeployError('OpenSSL failed while creating the WinRM client certificate') from exc
    os.chmod(key,stat.S_IRUSR|stat.S_IWUSR);os.chmod(cert,stat.S_IRUSR|stat.S_IWUSR);return cert,key

def _password_session(endpoint:str,user:str,password:str,transport:str,verify:bool):
    try:import winrm
    except ImportError as exc:raise WinRMDeployError('install pywinrm on the Controller before using winrm-prepare') from exc
    return winrm.Session(endpoint,auth=(user,password),transport=transport,server_cert_validation='validate' if verify else 'ignore',read_timeout_sec=90,operation_timeout_sec=60)

def prepare(args:argparse.Namespace)->dict[str,object]:
    user,host=_split_target(args.target); endpoint_host=f'[{host}]' if ':' in host else host;endpoint=f'https://{endpoint_host}:{args.port}/wsman'
    password=getpass.getpass('Senha administrativa do Windows (não será armazenada): ')
    if not password:raise WinRMDeployError('Windows administrator password is required')
    path=profile_path(host,Path(args.profile_dir) if args.profile_dir else None);cert,key=_generate_certificate(host,path.parent/path.stem)
    cert_der=subprocess.run(['openssl','x509','-in',str(cert),'-outform','der'],check=True,capture_output=True).stdout
    deploy_password=secrets.token_urlsafe(36)
    script=r"""
$ErrorActionPreference='Stop'
if (-not ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator required' }
Enable-PSRemoting -Force -SkipNetworkProfileCheck
$bytes=[Convert]::FromBase64String('__CERT__');$cert=[Security.Cryptography.X509Certificates.X509Certificate2]::new($bytes)
foreach($name in @('TrustedPeople','Root')){$store=[Security.Cryptography.X509Certificates.X509Store]::new($name,'LocalMachine');$store.Open('ReadWrite');$store.Add($cert);$store.Close()}
$secure=ConvertTo-SecureString '__PASSWORD__' -AsPlainText -Force;$account='capivara-deploy'
if(Get-LocalUser -Name $account -ErrorAction SilentlyContinue){Set-LocalUser -Name $account -Password $secure}else{New-LocalUser -Name $account -Password $secure -PasswordNeverExpires -AccountNeverExpires|Out-Null}
if(-not(Get-LocalGroupMember -Group 'Administrators' -Member $account -ErrorAction SilentlyContinue)){Add-LocalGroupMember -Group 'Administrators' -Member $account}
$credential=[Management.Automation.PSCredential]::new($account,$secure);Set-Item WSMan:\localhost\Service\Auth\Certificate -Value $true
Get-ChildItem WSMan:\localhost\ClientCertificate|Where-Object Subject -eq $cert.Subject|Remove-Item -Recurse -Force
New-Item WSMan:\localhost\ClientCertificate -Subject $cert.Subject -URI * -Issuer $cert.Thumbprint -Credential $credential -Force|Out-Null
'WINRM_READY'
""".replace('__CERT__',base64.b64encode(cert_der).decode()).replace('__PASSWORD__',deploy_password.replace("'","''"))
    try:response=_password_session(endpoint,user,password,args.transport,not args.insecure).run_ps(script)
    finally:password='';deploy_password=''
    if int(response.status_code) or b'WINRM_READY' not in bytes(response.std_out or b''):
        raise WinRMDeployError('WinRM preparation failed: '+bytes(response.std_err or b'').decode('utf-8','replace')[:2000])
    profile={'schema_version':1,'host':host,'port':args.port,'certificate':str(cert.relative_to(path.parent)),'private_key':str(key.relative_to(path.parent)),'server_certificate_validation':'ignore' if args.insecure else 'validate'}
    path.write_text(json.dumps(profile,indent=2)+'\n',encoding='utf-8');os.chmod(path,stat.S_IRUSR|stat.S_IWUSR)
    preflight=preflight_winrm(load_winrm_profile(host,path.parent),PyWinRMRunner())
    return {'status':'WINRM_READY','host':host,'port':args.port,'profile':str(path),'preflight':preflight}

def build_parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(description='Prepare secure WinRM certificate authentication');p.add_argument('target',help='Administrator@host');p.add_argument('--port',type=int,default=5986);p.add_argument('--transport',choices=('ntlm','kerberos'),default='ntlm');p.add_argument('--profile-dir');p.add_argument('--insecure',action='store_true',help='lab only: accept an untrusted HTTPS certificate');p.add_argument('--json',action='store_true');return p
def main(argv=None)->int:
    p=build_parser();args=p.parse_args(argv)
    try:result=prepare(args)
    except (WinRMDeployError,OSError,subprocess.CalledProcessError) as exc:p.exit(2,f'Erro: {exc}\n')
    print(json.dumps(result,ensure_ascii=False) if args.json else f"WINRM_READY {result['host']}:{result['port']}");return 0
if __name__=='__main__':raise SystemExit(main())
