"""Real ATM11 0.14 full-modpack boot -> owned systemd/JVM proof -> Controller health.

Runs ONLY with explicit opt-in on a disposable GitHub-hosted runner as root.
It creates a temporary systemd unit, customer database and manifests from the
physical, SHA-256 verified official 291 mods, never a production DSM runtime.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
for d in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard',ROOT/'agents/linux/runtime',ROOT/'agents/common'):
    if str(d) not in sys.path:sys.path.insert(0,str(d))

from tests import minecraft_serverpack_pending_publication_atomic_test as fixture_module
from agent_heartbeat_api import record_agent_heartbeat
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from content_bundle import normalize_bundle
from minecraft_serverpack_pending_commit import build_pending_bundle_commit
from minecraft_serverpack_physical_manifest import attest_serverpack_mods
from minecraft_serverpack_live_readiness import attest_live_serverpack_readiness

PACK_SHA='b8635562de0931eb5cadb51954c0fb78658033928ef54b5f73be6cae5c8897fa'
IID='pr855-controller-atomic'
AGENT='pr839-isolated-agent'
PORT=25596


def check_environment(root:Path):
    if not (os.geteuid()==0 and os.environ.get('GITHUB_ACTIONS')=='true'
            and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted'
            and os.environ.get('CAPIVARA_RUN_1013_REAL_SYSTEMD_HEALTH')=='1'):
        raise RuntimeError('refuse non-disposable real JVM attestation')
    if Path('/opt/dsm/runtime/hybrid-instance-storage').exists() or not Path('/run/systemd/system').is_dir():
        raise RuntimeError('refuse on installed DSM or non-systemd machine')
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise RuntimeError('unsafe official pack root')
    archive=root/'ServerFiles-0.14.0-beta.zip'
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=PACK_SHA:
            raise RuntimeError('official ZIP identity mismatch')
    args=root/'libraries/net/neoforged/neoforge/26.1.2.126/unix_args.txt'
    if not args.is_file():raise RuntimeError('NeoForge 26.1.2.126 not installed')
    if not (root/'eula.txt').is_file():raise RuntimeError('EULA not configured')
    jars=sorted((root/'mods').glob('*.jar'))
    if len(jars)!=291 or any(p.is_symlink() for p in jars):
        raise RuntimeError('not exactly 291 safe official mod JARs')
    props=(root/'server.properties').read_text()
    if 'server-ip=127.0.0.1' not in props or 'server-port=25596' not in props:
        raise RuntimeError('fixture must listen on loopback:25596')
    return args,jars


def prepare_publication(fixture,root:Path,jars:list[Path]):
    version='26.1.2.126'
    members=[];children=[]
    for n,path in enumerate(jars):
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        cid=f'mod-{n:03d}'
        artifact={
            'provider':'local','serverpack_child_v1':True,
            'ephemeral_upload':True,'bundle_parent_content_id':'atm11',
            'bundle_member':f'mods/{path.name}',
            'serverpack_loader':'neoforge','serverpack_loader_version':version,
            'sha256':digest,'size_bytes':path.stat().st_size,
        }
        members.append({'content_id':cid,'path':f'mods/{path.name}',
                        'required':True,'artifact':artifact})
        child=fixture_module.child('0.14.0-beta',version,'b')
        child.update(content_id=cid,target=f'mods/{cid}',artifact=artifact)
        children.append(child)
    content=fixture_module.bundle('0.14.0-beta',version,'b')
    content['members']=members
    canonical=normalize_bundle({**content,'instance_id':IID,'parent_content_id':'atm11'})
    physical=attest_serverpack_mods(root,instance_id=IID,content_id='atm11',bundle=content)
    assert physical['manifest_sha256']==canonical['manifest_sha256'] and physical['mod_count']==291
    pending=build_pending_bundle_commit(
        instance_id=IID,content_id='atm11',transfer_id='official-real-health',
        migration_plan_sha256='c'*64,expected_previous_revision=1,
        parent=fixture_module.parent('0.14.0-beta'),bundle=content,
        children=children,requested_by='customer')
    with fixture.backend.transaction() as c:
        c.execute('UPDATE instance_ports SET port=? WHERE instance_id=? AND name=? AND protocol=?',
                  (PORT,IID,'game','tcp'))
    repo=AgentInstanceProvisioningRepository(fixture.backend)
    state=repo.enqueue(
        agent_id=AGENT,instance_id=IID,environment_id='minecraft.java.neoforge',
        selector=f'26.1.2@{version}',
        selection={'runtime_definition':'minecraft.java.neoforge',
                   'version':'26.1.2','build':version},
        configuration={'minecraft_serverpack_migration':{
            'kind':'MinecraftServerPackMigration','instance_id':IID},
            'minecraft_serverpack_pending_bundle':pending,
            'minecraft_serverpack_execution_mode':'production'},
        desired_state='stopped',requested_by='customer')
    result=fixture.completed(state,pending)
    result['minecraft_serverpack_migration']['target_loader_version']=version
    result['minecraft_serverpack_migration']['transfer_id']=pending['transfer_id']
    result['minecraft_serverpack_migration']['physical_manifest']=physical
    applied=repo.apply_result(AGENT,result)
    if applied['status']!='completed':raise AssertionError(f'Controller CAS failed: {applied}')
    rows=[fixture.content.get(IID,'atm11')]+[fixture.content.get(IID,c['content_id']) for c in children]
    assert all(rows) and len(rows)==292
    retired=fixture.content.get(IID,'mod-a')
    assert retired and retired['desired_state']=='absent'
    reports=[{
        'instance_id':IID,'content_id':item['content_id'],
        'desired_revision':item['revision'],'desired_checksum':item['checksum'],
        'applied_revision':item['revision'],'applied_checksum':item['checksum'],
        'installed_version':item['version'] if item['desired_state']=='installed' else None,
        'status':'applied','security_state':'clean',
    } for item in [*rows,retired]]
    fixture.content.record_agent_state(AGENT,reports)
    bundle=fixture.content._bundle_row(IID,'atm11')
    assert bundle and bundle['manifest_sha256']==canonical['manifest_sha256']
    return bundle,physical


def unit_command(action:str,unit:str):
    return subprocess.run(['systemctl',action,unit],capture_output=True,text=True,timeout=30)


def live_attested_boot(root:Path,fixture,bundle:dict):
    unit=f'capivara-instance-{IID}.service'
    file=Path('/run/systemd/system')/unit
    sock=root/f'dsm1013-console-{IID}.sock'  # supervisor cmd binds its Agent instance ID
    if file.exists() or unit_command('is-active',unit).returncode==0:
        raise RuntimeError('refuse pre-existing service')
    launcher=root/'capivara-launch.args'
    if launcher.exists():raise RuntimeError('refuse pre-existing launcher target')
    args=root/'libraries/net/neoforged/neoforge/26.1.2.126/unix_args.txt'
    launcher.write_bytes(args.read_bytes())
    java=shutil.which('java')
    if not java:raise RuntimeError('missing Java')
    supervisor=ROOT/'agents/linux/runtime/console_supervisor.py'
    command=[sys.executable,str(supervisor),'--socket',str(sock),'--',
             java,'-Xms1024M','-Xmx5120M','-Djava.awt.headless=true',
             '@capivara-launch.args','nogui']
    assert any(IID in str(arg) for arg in command), 'supervisor process not bound to instance ID'
    if len(str(sock).encode())>100:raise RuntimeError('disposable UNIX socket path too long')
    props='''[Unit]
Description=DSM1013 official disposable ATM11 JVM health proof
[Service]
Type=simple
WorkingDirectory={work}
ExecStart={exec}
KillMode=control-group
Restart=no
TimeoutStopSec=15
'''.format(work=root,exec=' '.join(shlex.quote(arg) for arg in command))
    boot=None;report={};reasons=Counter();start=time.monotonic()
    try:
        file.write_text(props)
        subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
        subprocess.run(['systemctl','start',unit],check=True,timeout=30)
        while time.monotonic()-start<720:
            time.sleep(4)
            from minecraft_serverpack_boot_witness import observe_boot_witness
            boot=observe_boot_witness(root,instance_id=IID)
            if boot['status']=='boot_process_observed':
                report=attest_live_serverpack_readiness(
                    root,instance_id=IID,game_port=PORT,
                    bundle_revision=int(bundle['revision']),
                    manifest_sha256=bundle['manifest_sha256'])
                if report['status']=='functional_boot_attested':break
                reasons[report.get('reason','unknown')]+=1
            else:reasons[boot.get('reason','unknown')]+=1
            if unit_command('is-active',unit).returncode!=0:
                raise RuntimeError('JVM exited before functional attestation')
        else:raise RuntimeError(f'live systemd/JVM attestation timeout: {dict(reasons)}')
        assert boot is not None and report['status']=='functional_boot_attested'
        now=datetime.now(timezone.utc).isoformat()
        payload={'agent_id':AGENT,'instance_runtime_health':[{
            'instance_id':IID,'desired_state':'running',
            'observed_state':'running','reconcile_status':'healthy',
            'health':'healthy','operation_status':'idle','generated_at':now}],
            'minecraft_serverpack_observations':{
                'observed_at':now,'observations':[{
                    'instance_id':IID,'content_id':'atm11',
                    'bundle_revision':int(bundle['revision']),
                    'manifest_sha256':bundle['manifest_sha256'],
                    'status':'physical_runtime_verified',
                    'reason':'boot_not_observed','boot_verified':False,
                    'ready_for_release':False,
                    'boot_observation':boot,
                    'operational_attestation':report,
                }]}}
        received=record_agent_heartbeat(AGENT,payload,backend=fixture.backend)
        assert received['serverpack_observations_created']==1,received
        view=fixture.content.customer_view(IID)[0]['bundle_summary']
        assert view['health_gate']=='ready',view
        assert view['current_operational_attestation']=='observed',view
        assert view['runtime_process_observation']=='reported_running',view
        print('DSM1013_REAL_JVM_CONTROLLER_HEALTH_READY',json.dumps({
            'mods':291,'rev':bundle['revision'],
            'manifest_sha256':bundle['manifest_sha256'],
            'java_pid':report['java_pid'],'systemd':unit,
            'status':'ready','status_protocol':True,
            'release_authorized':False,'production_touched':False,
        }),flush=True)
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(5)
            conn.connect(str(sock))
            conn.sendall(b'stop\n')
            assert conn.recv(64).startswith(b'OK')
        until=time.monotonic()+100
        while time.monotonic()<until and unit_command('is-active',unit).returncode==0:
            time.sleep(2)
        assert unit_command('is-active',unit).returncode!=0,'JVM did not stop gracefully'
        payload['minecraft_serverpack_observations']['observed_at']=datetime.now(timezone.utc).isoformat()
        payload['minecraft_serverpack_observations']['observations']=[{
            **payload['minecraft_serverpack_observations']['observations'][0],
            'status':'unverified','reason':'current_jvm_stopped',
            'boot_observation':None,'operational_attestation':None}]
        payload['instance_runtime_health'][0].update(
            observed_state='stopped',reconcile_status='degraded',health='degraded')
        assert record_agent_heartbeat(AGENT,payload,backend=fixture.backend)['serverpack_observations_created']==1
        revoked=fixture.content.customer_view(IID)[0]['bundle_summary']
        assert revoked['health_gate']=='blocked',revoked
        print('DSM1013_REAL_JVM_CONTROLLER_HEALTH_REVOKED',json.dumps({
            'health_gate':'blocked','release_authorized':False,
            'production_touched':False}),flush=True)
        return {'systemd_functional_boot':True,'controller_ready_then_revoked':True,
                'mods':291,'manifest_sha256':bundle['manifest_sha256'],
                'release_authorized':False}
    finally:
        unit_command('stop',unit)
        file.unlink(missing_ok=True)
        subprocess.run(['systemctl','daemon-reload'],capture_output=True,timeout=30)
        subprocess.run(['systemctl','reset-failed',unit],capture_output=True,timeout=30)
        sock.unlink(missing_ok=True)
        launcher.unlink(missing_ok=True)


def main():
    root=Path(os.environ.get('DSM_1013_OFFICIAL_PACK_ROOT','')).resolve()
    _,jars=check_environment(root)
    fixture=fixture_module.AtomicPendingPublicationTest(
        methodName='test_completed_agent_result_publishes_bundle_in_same_completion_transaction')
    fixture.setUp()
    try:
        bundle,physical=prepare_publication(fixture,root,jars)
        assert physical['mod_count']==291
        output=live_attested_boot(root,fixture,bundle)
        (root/'systemd-health-evidence.json').write_text(json.dumps(output,indent=2)+'\n')
    finally:fixture.tearDown()


if __name__=='__main__':
    main()
