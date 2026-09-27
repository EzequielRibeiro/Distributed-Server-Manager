#!/usr/bin/env python3
"""Loopback HTTP transfer regression, using the production download route and Agent client.

Uses a small synthetic Server Pack; the separate real 495 MiB ZIP E2E is run
in isolated server homologation, not GitHub CI.
"""
from __future__ import annotations
import hashlib,importlib,json,os,ssl,subprocess,sys,tempfile,threading,unittest,urllib.error,urllib.request,zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'dashboard',ROOT/'database',ROOT/'core',ROOT/'agents/linux/runtime'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from backend import DatabaseConfig
from backend_factory import create_backend
from artifact_transfer_repository import ArtifactTransferRepository
from artifact_transfer_http import install_artifact_transfer_http
from agent_pairing_repository import AgentPairingRepository

class IsolatedHTTPTransferTest(unittest.TestCase):
 def test_official_zip_download_requires_auth_checks_hash_and_cleans_up(self):
  self._exercise_transport(tls_enabled=False)

 def test_tls_agent_download_requires_trusted_server_certificate(self):
  self._exercise_transport(tls_enabled=True)

 def _exercise_transport(self,tls_enabled):
  with tempfile.TemporaryDirectory(prefix='capivara-http-serverpack-') as td:
   root=Path(td);ctrl=root/'controller';ctrl.mkdir();data=root/'agent-data';data.mkdir()
   env={'CAPIVARA_AGENT_STATE_DIR':str(root/'agent-state'),'CAPIVARA_GAME_DATA_ROOT':str(data),'CAPIVARA_AGENT_GAME_DATA_ROOT':str(data)}
   if tls_enabled:
    cert=root/'server-cert.pem';key=root/'server-key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
      '-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost',
      '-addext','subjectAltName=IP:127.0.0.1,DNS:localhost'],
      check=True,capture_output=True)
    # Only the fixture server's public certificate is temporarily trusted.
    env['SSL_CERT_FILE']=str(cert)
   with patch.dict(os.environ,env):
    import content_upload_quarantine as quarantine
    importlib.reload(quarantine)  # module-level Agent roots depend on env
    import artifact_transfer_client as client
    importlib.reload(client)  # same process exercises HTTP then HTTPS
    backend=create_backend(DatabaseConfig(driver='sqlite',database=str(root/'controller.sqlite')));backend.initialize()
    with backend.transaction() as c:
     c.execute('INSERT INTO nodes(id,name,role) VALUES (?,?,?)',('node-c','Controller','controller'))
     c.execute('INSERT INTO nodes(id,name,role) VALUES (?,?,?)',('node-a','Agent','agent'))
     c.execute('INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)',('ctrl','node-c','Controller'))
     c.execute('INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)',('agent','ctrl','node-a','Agent','active'))
     customer=c.execute('INSERT INTO customers(controller_id,name) VALUES (?,?)',('ctrl','Customer'))
     c.execute('INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)',('scratch','node-a','minecraft','Scratch','stopped','ctrl','agent',customer.lastrowid))
    repo=ArtifactTransferRepository(backend,ctrl)
    source=root/'official.zip'
    with zipfile.ZipFile(source,'w') as z:
     z.writestr('mods/demo.jar','dummy-archive-fixture')
     z.writestr('config/server.toml','enabled=true')
    expected=hashlib.sha256(source.read_bytes()).hexdigest()
    class Legacy:
     DSM_ROOT=ctrl;DATABASE_FILE=str(root/'controller.sqlite')
     dashboard_repository=staticmethod(lambda _:SimpleNamespace(backend=backend))
     class DashboardHandler(BaseHTTPRequestHandler):
      def log_message(self,*args):pass
      def send_json(self,status,payload):
       blob=json.dumps(payload).encode()
       self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob)
      def do_GET(self):self.send_json(404,{'error':'not_found'})
      def do_POST(self):self.send_json(404,{'error':'not_found'})
    install_artifact_transfer_http(Legacy,lambda _:None)
    def auth(self,credential_id,credential_secret,fingerprint):
     if (credential_id,credential_secret,fingerprint)==('scratch-id','scratch-secret','scratch-fingerprint'):
      return {'agent_id':'agent'}
     return None
    with patch.object(AgentPairingRepository,'authenticate',auth):
     server=ThreadingHTTPServer(('127.0.0.1',0),Legacy.DashboardHandler)
     if tls_enabled:
      ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
      ctx.load_cert_chain(certfile=str(cert),keyfile=str(key))
      server.socket=ctx.wrap_socket(server.socket,server_side=True)
     thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
     try:
      item=repo.create(agent_id='agent',instance_id='scratch',customer_id=customer.lastrowid,
       direction='controller_to_agent',purpose='content_upload',filename=source.name,requested_by='test')
      with source.open('rb') as handle:item=repo.stage_from_controller(item['transfer_id'],handle,source.stat().st_size)
      self.assertEqual(item['sha256'],expected)
      command=repo.command_for_agent('agent')
      scheme='https' if tls_enabled else 'http'
      url=f'{scheme}://127.0.0.1:{server.server_address[1]}/api/agent/artifacts/download?transfer_id={item["transfer_id"]}'
      # urllib caches its default opener across test cases. Construct an
      # explicitly trusted context for this *separate* unauthorized probe.
      request_context=ssl.create_default_context(cafile=str(cert)) if tls_enabled else None
      with self.assertRaises(urllib.error.HTTPError) as denied:
       urllib.request.urlopen(url,timeout=3,context=request_context)
      self.assertEqual(denied.exception.code,401)
      config={'controller_url':f'{scheme}://127.0.0.1:{server.server_address[1]}',
       'credential_id':'scratch-id','credential_secret':'scratch-secret','fingerprint':'scratch-fingerprint'}
      if tls_enabled:
       # An untrusted certificate must not silently downgrade or download.
       with patch.dict(os.environ,{'SSL_CERT_FILE':str(root/'missing-ca.pem')}):
        untrusted_path=root/'untrusted-download.zip'
        with self.assertRaises(ssl.SSLCertVerificationError):
         client._get(config,item['transfer_id'],untrusted_path)
        self.assertFalse(untrusted_path.exists())
      report=client.handle_command(config,command)
      self.assertEqual(report['status'],'completed',report)
      self.assertEqual(report['sha256'],expected)
      self.assertEqual(report['archive_entries'],2)
      dest=data/report['destination_ref'];self.assertEqual(hashlib.sha256(dest.read_bytes()).hexdigest(),expected)
      accepted=repo.apply_agent_result('agent',report)
      self.assertEqual(accepted['status'],'completed')
      self.assertEqual(accepted['destination_ref'],report['destination_ref'])
      repo.reject_content_upload(item['transfer_id'],'scratch rejected preview')
      cleanup=repo.command_for_agent('agent')
      self.assertEqual(cleanup['purpose'],'content_upload_cleanup')
      self.assertEqual(client.handle_command(config,cleanup)['status'],'completed')
      self.assertFalse(dest.exists())
     finally:server.shutdown();server.server_close();thread.join(timeout=5);backend.close()

if __name__=='__main__':unittest.main()
