#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,io,json,os,sys,zipfile
from pathlib import Path

PARSER=argparse.ArgumentParser()
PARSER.add_argument('--platform',choices=('linux','windows'),required=True)
PARSER.add_argument('--work-root',required=True)
PARSER.add_argument('--output',required=True)
ARGS=PARSER.parse_args()
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(ARGS.work_root).resolve();WORK.mkdir(parents=True,exist_ok=True)
STATE=WORK/'agent-state';GAME_DATA=WORK/'game-data';RUNTIMES=WORK/'runtimes';CONTROLLER=WORK/'controller'
for p in (STATE,GAME_DATA,RUNTIMES,CONTROLLER):p.mkdir(parents=True,exist_ok=True)
os.environ['CAPIVARA_AGENT_STATE_DIR']=str(STATE)
os.environ['CAPIVARA_GAME_DATA_ROOT']=str(GAME_DATA)
os.environ['CAPIVARA_AGENT_GAME_DATA_ROOT']=str(GAME_DATA)
os.environ['CAPIVARA_INSTANCE_SYSTEMD_DIR']=str(WORK/'systemd')
os.environ['PROGRAMDATA']=str(WORK/'programdata')
os.environ['ProgramFiles']=str(WORK/'programfiles')
RUNTIME=ROOT/'agents'/ARGS.platform/'runtime'
sys.path[:0]=[str(RUNTIME),str(ROOT/'database'),str(ROOT/'core'),str(ROOT/'dashboard'),str(ROOT)]

from backend import DatabaseConfig
from backend_factory import create_backend
from content_repository import ContentRepository
from artifact_transfer_repository import ArtifactTransferRepository
from agent_heartbeat_api import record_agent_heartbeat
import content_client,content_provider,content_upload_quarantine,instance_runtime,runtime_materialization

AGENT='agent-u10'
CONFIG={'agent_id':AGENT}
RUNNING:dict[str,bool]={}
DOCTOR:dict[str,list[bool]]={}
BLOCKED_NAMES:set[str]=set()

def fake_status(config,instance_id):return {'observed_state':'running' if RUNNING.get(instance_id,False) else 'stopped'}
def fake_lifecycle(config,instance_id,action):
 if action=='stop':RUNNING[instance_id]=False
 elif action in {'start','restart'}:RUNNING[instance_id]=True
 return {'observed_state':'running' if RUNNING.get(instance_id,False) else 'stopped'}
def fake_doctor(config,instance_id):
 seq=DOCTOR.get(instance_id) or []
 return {'ready':seq.pop(0) if seq else True}
instance_runtime.status=fake_status;instance_runtime.lifecycle=fake_lifecycle;instance_runtime.doctor=fake_doctor

if ARGS.platform=='linux':
 import privileged_materialization
 class FakeMaterializer:
  def inspect(self,spec):return {'exists':True,'owned':True,'matches':True}
  def apply(self,spec):return {'action':'materialize','changed':True}
  def remove(self,spec):return {'action':'remove','changed':True}
 runtime_materialization.resolve_materializer=lambda spec:FakeMaterializer()
 privileged_materialization.materialize=lambda config,spec:{'spec':spec,'operation':{'action':'materialize','changed':True}}

def fixture_resolver(artifact,stage,game_data_root):
 candidate=(Path(game_data_root)/str(artifact.get('package_id') or '')).resolve();candidate.relative_to(Path(game_data_root).resolve())
 if not candidate.exists():raise FileNotFoundError(candidate)
 return candidate
content_provider.register_provider('modrinth',fixture_resolver,replace=True)

def scan(path,context=None):
 name=Path(path).name
 if name in BLOCKED_NAMES:
  raise content_client.ContentSecurityRejected({'security_state':'blocked','engine':'yara-x','policy_version':1,'reason':'U10 blocked fixture','matches':[{'rule':'u10_block','tags':['malware','block']}]})
 return {'security_state':'clean','engine':'yara-x','policy_version':1,'reason':None,'matches':[]}
content_client.require_clean=scan

backend=create_backend(DatabaseConfig(driver='sqlite',database=str(CONTROLLER/'capivara.db')));backend.initialize()
with backend.transaction() as c:
 c.execute('INSERT INTO nodes(id,name,role) VALUES (?,?,?)',('ctrl-node','Controller','controller'))
 c.execute('INSERT INTO nodes(id,name,role) VALUES (?,?,?)',('agent-node','Agent','agent'))
 c.execute('INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)',('ctrl','ctrl-node','Controller'))
 c.execute('INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)',(AGENT,'ctrl','agent-node','Agent U10','active'))
 customer=c.execute('INSERT INTO customers(controller_id,name) VALUES (?,?)',('ctrl','Customer U10'));CUSTOMER_ID=int(customer.lastrowid)
 for iid in ('paper-a','paper-b','neo-a','pack-a','upload-a'):
  c.execute('INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)',(iid,'agent-node','minecraft',iid,'stopped','ctrl',AGENT,CUSTOMER_ID))
repo=ContentRepository(backend);repo.initialize()

def projection(kind):
 directory='plugins' if kind=='plugin' else 'mods'
 return {'adapter':'minecraft-java','types':{kind:{'directory':directory,'extensions':['.jar']}}}

def register_instance(iid,environment,kind):
 runtime=RUNTIMES/iid;runtime.mkdir(parents=True,exist_ok=True);state=STATE/'instance-state'/iid;state.mkdir(parents=True,exist_ok=True)
 exe=runtime/('server.exe' if ARGS.platform=='windows' else 'server.bin');exe.write_bytes(b'executable')
 spec={'instance_id':iid,'agent_id':AGENT,'game_id':'minecraft','environment_id':environment,'runtime_id':iid,'working_directory':str(runtime),'path':str(runtime),'executable':str(exe),'arguments':[],'environment':{},'desired_state':'stopped','instance_state_root':str(state),'content_projection':projection(kind)}
 if ARGS.platform=='linux':spec.update({'adapter':'systemd','user':'capivara-instance'})
 else:spec.update({'adapter':'windows-process','executable_scope':'working-directory'})
 instance_runtime.register_instance(spec)
 return runtime
PAPER_A=register_instance('paper-a','minecraft.java.paper','plugin')
PAPER_B=register_instance('paper-b','minecraft.java.paper','plugin')
NEO=register_instance('neo-a','minecraft.java.neoforge','mod')
PACK=register_instance('pack-a','minecraft.java.fabric','mod')
UPLOAD=register_instance('upload-a','minecraft.java.paper','plugin')

def write_fixture(rel,data):
 p=GAME_DATA/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p

def remote_artifact(rel,data,*,archive=False):
 write_fixture(rel,data)
 out={'provider':'modrinth','package_id':rel,'url':'https://fixture.invalid/'+rel,'filename':Path(rel).name,'sha512':hashlib.sha512(data).hexdigest()}
 if archive:out['archive']=True
 return out

def jar_bytes(label):
 bio=io.BytesIO()
 with zipfile.ZipFile(bio,'w') as z:z.writestr('META-INF/MANIFEST.MF','Manifest-Version: 1.0\n');z.writestr('payload.txt',label)
 return bio.getvalue()

def pack_bytes(label):
 bio=io.BytesIO()
 with zipfile.ZipFile(bio,'w') as z:
  z.writestr('overrides/config/pack.toml','layer=base-'+label+'\n')
  z.writestr('server-overrides/config/pack.toml','layer=server-'+label+'\n')
 return bio.getvalue()

def jar_payload(path):
 with zipfile.ZipFile(path) as z:return z.read('payload.txt').decode('utf-8')

def assignment_raw(iid,cid,ctype,version,artifact,order=0,enabled=True):
 return {'instance_id':iid,'content_id':cid,'content_type':ctype,'provider':artifact.get('provider'),'version':version,'artifact':artifact,'activation_order':order,'activation_state':'enabled' if enabled else 'disabled'}

def current_raw(item,**changes):
 keys=('instance_id','content_id','content_type','version','provider','target','artifact','provenance','metadata','dependencies','conflicts','activation_order','activation_state','desired_state')
 raw={k:item.get(k) for k in keys if item.get(k) is not None};raw.update(changes);return raw

def heartbeat_apply():
 response=record_agent_heartbeat(AGENT,{'agent_id':AGENT,'content_state':content_client.content_state()},backend=backend,root=ROOT)
 commands=response['content_commands'];reports=content_client.apply_content_commands(CONFIG,commands) if commands else []
 after=record_agent_heartbeat(AGENT,{'agent_id':AGENT,'content_state':reports},backend=backend,root=ROOT) if reports else response
 return commands,reports,after

def settle(max_rounds=6):
 all_reports=[]
 for _ in range(max_rounds):
  commands,reports,after=heartbeat_apply();all_reports.extend(reports)
  if not commands and not after.get('content_commands'):break
  if after.get('content_commands'):
   reports2=content_client.apply_content_commands(CONFIG,after['content_commands']);all_reports.extend(reports2)
   record_agent_heartbeat(AGENT,{'agent_id':AGENT,'content_state':reports2},backend=backend,root=ROOT)
 return all_reports

def native(runtime,folder,cid):return runtime/folder/f'capivara-{cid}.jar'

# Paper + plugin ordering, enable/disable and isolation.
p1v1=jar_bytes('paper-a-p1-v1');p2v1=jar_bytes('paper-a-p2-v1');pbv1=jar_bytes('paper-b-v1')
repo.put(assignment_raw('paper-a','p1','plugin','1',remote_artifact('fixtures/p1-v1.jar',p1v1),20),requested_by='u10')
repo.put(assignment_raw('paper-a','p2','plugin','1',remote_artifact('fixtures/p2-v1.jar',p2v1),10),requested_by='u10')
repo.put(assignment_raw('paper-b','p1','plugin','1',remote_artifact('fixtures/pb-v1.jar',pbv1),0),requested_by='u10')
settle()
assert native(PAPER_A,'plugins','p1').read_bytes()==p1v1 and native(PAPER_A,'plugins','p2').read_bytes()==p2v1
assert native(PAPER_B,'plugins','p1').read_bytes()==pbv1
from content_activation_projection import activation_snapshot
assert [x['content_id'] for x in activation_snapshot('paper-a')['entries']]==['p2','p1']
cur=repo.get('paper-a','p1');repo.put(current_raw(cur,activation_state='disabled'),requested_by='u10');settle();assert not native(PAPER_A,'plugins','p1').exists();assert native(PAPER_A,'plugins','p2').exists()
cur=repo.get('paper-a','p1');repo.put(current_raw(cur,activation_state='enabled',activation_order=5),requested_by='u10');settle();assert native(PAPER_A,'plugins','p1').read_bytes()==p1v1;assert [x['content_id'] for x in activation_snapshot('paper-a')['entries']]==['p1','p2']

# NeoForge + mods: install, disable/enable, reorder, update and explicit rollback.
modv1=jar_bytes('neo-mod-v1');sidev1=jar_bytes('neo-side-v1')
repo.put(assignment_raw('neo-a','mod-main','mod','1',remote_artifact('fixtures/mod-v1.jar',modv1),10),requested_by='u10')
repo.put(assignment_raw('neo-a','mod-side','mod','1',remote_artifact('fixtures/mod-side-v1.jar',sidev1),20),requested_by='u10');settle()
assert native(NEO,'mods','mod-main').read_bytes()==modv1 and native(NEO,'mods','mod-side').read_bytes()==sidev1
assert [x['content_id'] for x in activation_snapshot('neo-a')['entries']]==['mod-main','mod-side']
neo_old=repo.get('neo-a','mod-main');repo.put(current_raw(neo_old,activation_state='disabled'),requested_by='u10');settle();assert not native(NEO,'mods','mod-main').exists()
neo_disabled=repo.get('neo-a','mod-main');repo.put(current_raw(neo_disabled,activation_state='enabled',activation_order=30),requested_by='u10');settle();assert [x['content_id'] for x in activation_snapshot('neo-a')['entries']]==['mod-side','mod-main']
neo_before_update=repo.get('neo-a','mod-main');modv2=jar_bytes('neo-mod-v2');repo.put(current_raw(neo_before_update,version='2',artifact=remote_artifact('fixtures/mod-v2.jar',modv2),provenance={'minecraft_provider':{'project_id':'neo-mod','version_id':'2'}}),requested_by='u10');settle();assert jar_payload(native(NEO,'mods','mod-main'))=='neo-mod-v2'
repo.rollback('neo-a','mod-main',neo_before_update['revision'],requested_by='u10',reason='e2e');settle();assert jar_payload(native(NEO,'mods','mod-main'))=='neo-mod-v1';assert [x['content_id'] for x in activation_snapshot('neo-a')['entries']]==['mod-side','mod-main']

# Paper update fails readiness, Agent rolls back, heartbeat creates and applies Controller rollback revision.
p1v2=jar_bytes('paper-a-p1-v2');old=repo.get('paper-a','p1');updated=repo.put(current_raw(old,version='2',artifact=remote_artifact('fixtures/p1-v2.jar',p1v2),provenance={'minecraft_provider':{'project_id':'p1','version_id':'2'}}),requested_by='u10')['assignment']
RUNNING['paper-a']=True;DOCTOR['paper-a']=[False,True]
commands,reports,after=heartbeat_apply();rolled=[r for r in reports if r.get('content_id')=='p1'][0]
assert rolled['status']=='rolled_back' and rolled['applied_revision']==old['revision'];assert native(PAPER_A,'plugins','p1').read_bytes()==p1v1;assert native(PAPER_B,'plugins','p1').read_bytes()==pbv1
rollback_commands=after['content_commands'];assert any(c.get('content_id')=='p1' and c.get('version')=='1' for c in rollback_commands)
reports2=content_client.apply_content_commands(CONFIG,rollback_commands);record_agent_heartbeat(AGENT,{'agent_id':AGENT,'content_state':reports2},backend=backend,root=ROOT);RUNNING['paper-a']=False
assert repo.get('paper-a','p1')['version']=='1' and repo.get('paper-a','p1')['revision']>updated['revision']

# U7 blocked revision cannot replace currently active clean content and becomes terminal.
blocked=jar_bytes('blocked-v3');repo.put(current_raw(repo.get('paper-a','p1'),version='3',artifact=remote_artifact('fixtures/blocked-v3.jar',blocked)),requested_by='u10');BLOCKED_NAMES.add('blocked-v3.jar')
commands,reports,after=heartbeat_apply();blocked_report=[r for r in reports if r.get('content_id')=='p1'][0];assert blocked_report['status']=='security_blocked';assert native(PAPER_A,'plugins','p1').read_bytes()==p1v1;assert not any(c.get('instance_id')=='paper-a' and c.get('content_id')=='p1' for c in after.get('content_commands',[]));BLOCKED_NAMES.clear()

# Provider-backed composed modpack install, update, manifest diff and explicit rollback.
a1=jar_bytes('pack-a-v1');a2=jar_bytes('pack-a-v2');b1=jar_bytes('pack-b-v1');pa1=remote_artifact('fixtures/pack-a-v1.jar',a1);pa2=remote_artifact('fixtures/pack-a-v2.jar',a2);pb1=remote_artifact('fixtures/pack-b-v1.jar',b1)
parent1=assignment_raw('pack-a','pack','modpack','1',remote_artifact('fixtures/pack-v1.zip',pack_bytes('v1'),archive=True))
bundle1={'provider':'modrinth','provider_project_id':'pack-project','provider_version_id':'v1','minecraft_version':'1.21.1','loader_id':'fabric','loader_version':'0.16.0','manifest_kind':'mrpack-v1','members':[{'content_id':'a','path':'mods/a.jar','required':True,'artifact':pa1}],'override_roots':['overrides','server-overrides']}
child1=assignment_raw('pack-a','a','mod','1',pa1);repo.put_bundle(parent1,bundle1,[child1],requested_by='u10');settle();assert native(PACK,'mods','a').read_bytes()==a1;assert (PACK/'config'/'pack.toml').read_text()=='layer=server-v1\n'
parent2=assignment_raw('pack-a','pack','modpack','2',remote_artifact('fixtures/pack-v2.zip',pack_bytes('v2'),archive=True))
bundle2={'provider':'modrinth','provider_project_id':'pack-project','provider_version_id':'v2','minecraft_version':'1.21.1','loader_id':'fabric','loader_version':'0.16.0','manifest_kind':'mrpack-v1','members':[{'content_id':'a','path':'mods/a.jar','required':True,'artifact':pa2},{'content_id':'b','path':'mods/b.jar','required':True,'artifact':pb1}],'override_roots':['overrides','server-overrides']}
assert repo.bundle_diff('pack-a','pack',bundle2)=={'added':['b'],'removed':[],'updated':['a'],'unchanged':[]}
repo.put_bundle(parent2,bundle2,[assignment_raw('pack-a','a','mod','2',pa2),assignment_raw('pack-a','b','mod','1',pb1)],requested_by='u10');settle();assert native(PACK,'mods','a').read_bytes()==a2 and native(PACK,'mods','b').read_bytes()==b1;assert (PACK/'config'/'pack.toml').read_text()=='layer=server-v2\n'
repo.rollback_bundle('pack-a','pack',1,requested_by='u10',reason='e2e');settle();assert native(PACK,'mods','a').read_bytes()==a1 and not native(PACK,'mods','b').exists();assert (PACK/'config'/'pack.toml').read_text()=='layer=server-v1\n'

# External Upload: Controller spool -> Agent quarantine -> local UCP assignment -> U7 -> native plugin projection.
upload_bytes=jar_bytes('external-upload');transfers=ArtifactTransferRepository(backend,CONTROLLER);item=transfers.create(agent_id=AGENT,instance_id='upload-a',customer_id=CUSTOMER_ID,direction='controller_to_agent',purpose='content_upload',filename='upload.jar',requested_by='u10');item=transfers.stage_from_controller(item['transfer_id'],io.BytesIO(upload_bytes),len(upload_bytes));command=transfers.command_for_agent(AGENT);assert command and command['transfer_id']==item['transfer_id']
dest=content_upload_quarantine.quarantine_destination('upload-a',item['transfer_id'],'upload.jar');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(upload_bytes);inspection=content_upload_quarantine.validate_quarantine_archive(dest);ref=content_upload_quarantine.quarantine_relative_path(dest)
completed=transfers.apply_agent_result(AGENT,{'transfer_id':item['transfer_id'],'status':'completed','transferred_bytes':len(upload_bytes),'destination_ref':ref,'sha256':item['sha256'],'archive_type':inspection['archive_type'],'archive_entries':inspection['entries']});assert completed['status']=='completed'
repo.put({'instance_id':'upload-a','content_id':'uploaded','content_type':'plugin','provider':'local','version':'upload-1','artifact':{'provider':'local','package_id':ref,'filename':'upload.jar','sha256':item['sha256']}},requested_by='u10');settle();assert native(UPLOAD,'plugins','uploaded').read_bytes()==upload_bytes

summary={
 'platform':ARGS.platform,
 'paper_order':[x['content_id'] for x in activation_snapshot('paper-a')['entries']],
 'paper_rollback_version':repo.get('paper-a','p1')['provenance'].get('rollback',{}).get('restored_revision'),
 'paper_blocked_payload':jar_payload(native(PAPER_A,'plugins','p1')),
 'paper_b_payload':jar_payload(native(PAPER_B,'plugins','p1')),
 'neo_payload':jar_payload(native(NEO,'mods','mod-main')),
 'neo_side_payload':jar_payload(native(NEO,'mods','mod-side')),
 'neo_order':[x['content_id'] for x in activation_snapshot('neo-a')['entries']],
 'pack_revision':int(repo._bundle_row('pack-a','pack')['revision']),
 'pack_a_payload':jar_payload(native(PACK,'mods','a')),
 'pack_b_present':native(PACK,'mods','b').exists(),
 'pack_config':(PACK/'config'/'pack.toml').read_text(),
 'upload_payload':jar_payload(native(UPLOAD,'plugins','uploaded')),
 'blocked_state':repo.agent_state_for_instance('paper-a')['p1']['security_state'],
 'isolation':jar_payload(native(PAPER_B,'plugins','p1'))=='paper-b-v1',
}
Path(ARGS.output).write_text(json.dumps(summary,sort_keys=True)+'\n',encoding='utf-8')
backend.close()
