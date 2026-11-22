#!/usr/bin/env python3
"""Two running Linux Agent daemons + isolated TLS Controller native DayZ bootstrap.

Uses production enroll/heartbeat/queue code and real Agent background loops,
but only fixture adapters and tempfile runtime paths (never systemctl or DayZ).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import HTTPServer
from pathlib import Path
import ssl

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"tests",ROOT/"database",ROOT/"dashboard",
          ROOT/"agents"/"common",ROOT/"agents"/"linux"/"runtime"):
    if str(p) not in sys.path:sys.path.insert(0,str(p))


def _daemon_worker(spec):
    import agent as linux_agent
    import instance_runtime
    import privileged_materialization

    state_file=Path(spec["state_file"])

    class FixtureAdapter:
        name="isolated-dayz-fixture"
        def status(self, record):
            running=state_file.is_file()
            return {"adapter":self.name,"available":True,
                    "active_state":"active" if running else "inactive"}
        def start(self, record):
            changed=not state_file.is_file()
            state_file.parent.mkdir(parents=True,exist_ok=True)
            state_file.write_text("started",encoding="utf-8")
            return {"changed":changed,"idempotent":not changed,
                    "state":self.status(record)}

    instance_runtime.resolve_adapter=lambda _record:FixtureAdapter()
    privileged_materialization.repair_dayz_dlc_ownership=lambda *_args,**_kwargs:None

    # Real daemon lifecycle, heartbeat and queues; no unrelated systemd,
    # reconcile, console, content-update, or finalization side effects.
    linux_agent.reconcile_all=lambda _config:None
    linux_agent.recover_interrupted_operations=lambda _config:[]
    linux_agent.start_console_stream=lambda _config:None
    linux_agent.start_content_update_inventory=lambda *_args,**_kwargs:None

    class NullFinalizationSupervisor:
        def launch(self,**_kwargs):return "disabled"

    linux_agent.FinalizationWorkerSupervisor=NullFinalizationSupervisor
    instance_runtime.register_instance(spec["record"])
    linux_agent.run_forever()


class TwoAgentDaemonBootstrapTest(unittest.TestCase):
    def test_real_daemon_heartbeats_and_crash_recovery(self):
        from backend import DatabaseConfig
        from backend_factory import create_backend
        from registry import installation_profile_identity
        from registry_repository import RegistryRepository
        from agent_pairing_repository import AgentPairingRepository
        from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
        from dayz_native_restart_repository import DayZNativeRestartRepository
        from maintenance_repository import MaintenanceRepository
        from agent_runtime_repository import AgentRuntimeRepository
        from external_controller_agent_network_e2e import ControllerHandler
        from maintenance_controller_agent_e2e import _certificate

        with tempfile.TemporaryDirectory(prefix="dsm-dayz-daemons-") as folder:
            root=Path(folder)
            backend=create_backend(DatabaseConfig(
                driver="sqlite",database=str(root/"controller.db"),
            ))
            backend.initialize()
            server=None
            thread=None
            workers={}
            logs={}
            try:
                identity=installation_profile_identity(
                    RegistryRepository(backend),
                    profile="controller",hostname="dayz-daemon-ci-controller",
                )
                controller=str(identity["controller_id"])
                cert,key=_certificate(root)
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1",0))
                    port=sock.getsockname()[1]

                ControllerHandler.backend=backend
                ControllerHandler.before_heartbeat=None
                server=HTTPServer(("127.0.0.1",port),ControllerHandler)
                context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version=ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(str(cert),str(key))
                server.socket=context.wrap_socket(server.socket,server_side=True)
                thread=threading.Thread(target=server.serve_forever,daemon=True)
                thread.start()

                pairing=AgentPairingRepository(backend)
                agents=("dayz-daemon-agent-a","dayz-daemon-agent-b")
                instances=("dayz-daemon-instance-a","dayz-daemon-instance-b")
                missions=("regular.namalsk","hardcore.namalsk")
                configs={}

                with backend.transaction() as db:
                    db.execute(
                        "INSERT INTO customers(id,controller_id,name,status) VALUES(?,?,?,?)",
                        (1,controller,"Daemon isolated customer","active"),
                    )
                for index,(aid,iid,mission) in enumerate(zip(agents,instances,missions)):
                    token=pairing.issue_token(controller_id=controller,created_by="isolated-test")
                    node="dayz-daemon-node-"+str(index)
                    agent_root=root/aid
                    state=agent_root/"state"
                    work=agent_root/"serverfiles"
                    mission_dir=work/"mpmissions"/mission
                    mission_dir.mkdir(parents=True)
                    (work/"serverDZ.cfg").write_text(
                        'class Missions { class DayZ { template="'+mission+'"; }; };\n',
                        encoding="utf-8",
                    )
                    cfg={
                        "agent_id":aid,"node_id":node,"name":aid,
                        "fingerprint":"sha256:"+aid,
                        "controller_url":f"https://localhost:{port}",
                        "pairing_token":token.token,
                        "capivara_version":"isolated-daemon-native-ci",
                        "heartbeat_interval_seconds":10,
                        "reconcile_interval_seconds":180,
                    }
                    config_file=agent_root/"agent.json"
                    config_file.write_text(json.dumps(cfg),encoding="utf-8")
                    record={
                        "instance_id":iid,"agent_id":aid,"game_id":"dayz",
                        "adapter":"isolated-dayz-fixture",
                        "working_directory":str(work),
                        "arguments":["-config=serverDZ.cfg"],
                        "observed_state":"stopped",
                    }
                    configs[aid]={
                        "config_file":str(config_file),"state_dir":str(state),
                        "state_file":str(agent_root/"started.flag"),
                        "record":record,
                    }

                def spawn(aid):
                    settings=configs[aid]
                    env=dict(os.environ)
                    env["CAPIVARA_AGENT_CONFIG"]=settings["config_file"]
                    env["CAPIVARA_AGENT_STATE_DIR"]=settings["state_dir"]
                    env["SSL_CERT_FILE"]=str(cert)
                    log=open(root/aid/"daemon.log","a",encoding="utf-8")
                    logs[aid]=log
                    proc=subprocess.Popen(
                        [sys.executable,"-u",str(Path(__file__).resolve()),
                         "--daemon-worker",json.dumps({
                             "record":settings["record"],
                             "state_file":settings["state_file"],
                         })],
                        cwd=ROOT,env=env,stdin=subprocess.DEVNULL,
                        stdout=log,stderr=subprocess.STDOUT,
                    )
                    workers[aid]=proc
                    return proc

                def wait_for(predicate,label,timeout=105):
                    deadline=time.monotonic()+timeout
                    while time.monotonic()<deadline:
                        for aid,proc in workers.items():
                            self.assertIsNone(proc.poll(),f"{aid} unexpectedly exited while waiting for {label}")
                        if predicate():return
                        time.sleep(0.15)
                    details={}
                    for aid in agents:
                        log_path=root/aid/"daemon.log"
                        details[aid]=log_path.read_text(encoding="utf-8",errors="replace")[-2200:] if log_path.exists() else "no log"
                    self.fail(f"Timed out waiting for {label}: {details}")

                for aid in agents:spawn(aid)

                runtime_states=AgentRuntimeRepository(backend)
                def active_agents():
                    try:
                        return all(
                            str(runtime_states.snapshot(aid,refresh_health=False).get("status") or "").lower()=="active"
                            for aid in agents
                        )
                    except (KeyError,ValueError):
                        return False
                wait_for(active_agents,"both authenticated daemons",timeout=40)

                with backend.transaction() as db:
                    for index,(aid,iid) in enumerate(zip(agents,instances)):
                        db.execute(
                            "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id)"
                            " VALUES(?,?,?,?,?,?,?,?)",
                            (iid,"dayz-daemon-node-"+str(index),"dayz",iid,"offline",controller,aid,1),
                        )
                maintenance=MaintenanceRepository(backend)
                lifecycle=AgentInstanceRuntimeRepository(backend)
                native=DayZNativeRestartRepository(backend)
                commands={}
                for aid,iid in zip(agents,instances):
                    maintenance.set_policy(iid,{
                        "enabled":True,"schedule_mode":"interval",
                        "interval_seconds":28800,
                        "warning_offsets_seconds":[],"broadcast_enabled":False,
                    })
                    commands[aid]=lifecycle.enqueue(
                        agent_id=aid,instance_id=iid,action="start",
                        requested_by="isolated-daemon-authorized",
                    )

                # Wait for real authenticated Agent heartbeats and ACKs.
                # The next heartbeat interval leaves a window to crash Agent A.
                def prepared_both():
                    for aid,iid in zip(agents,instances):
                        due=maintenance.snapshot(iid)["state"]["next_due_at"]
                        item=native.for_instance_due(iid,due)
                        if item is None or item.get("status")!="completed":
                            return False
                    return True
                wait_for(prepared_both,"native ACK from both Agents")

                first=agents[0]
                # Crash/restart after native ACK. Agent-owned preparation history
                # must survive, and neither game may have started prematurely.
                self.assertFalse(Path(configs[first]["state_file"]).exists(),
                                 "instance started before Agent crash gate")
                workers[first].kill()
                workers[first].wait(timeout=5)
                logs[first].close()
                spawn(first)

                def both_started():
                    return all(
                        lifecycle.snapshot(commands[aid]["command_id"])["status"]=="completed"
                        for aid in agents
                    )
                wait_for(both_started,"two native-guarded starts after recovery",timeout=110)

                for aid,mission in zip(agents,missions):
                    flag=Path(configs[aid]["state_file"])
                    self.assertTrue(flag.is_file(),aid)
                    xml=Path(configs[aid]["record"]["working_directory"])/"mpmissions"/mission/"db"/"messages.xml"
                    self.assertTrue(xml.is_file(),str(xml))
                    self.assertIn("<shutdown>1</shutdown>",xml.read_text(encoding="utf-8"))
                self.assertNotEqual(
                    configs[agents[0]]["state_dir"],configs[agents[1]]["state_dir"],
                )
            finally:
                for proc in workers.values():
                    if proc.poll() is None:
                        proc.terminate()
                        try:proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=5)
                for handle in logs.values():
                    if not handle.closed:handle.close()
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:thread.join(timeout=2)
                ControllerHandler.backend=None
                ControllerHandler.before_heartbeat=None
                backend.close()


if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--daemon-worker":
        _daemon_worker(json.loads(sys.argv[2]))
    else:
        unittest.main()
