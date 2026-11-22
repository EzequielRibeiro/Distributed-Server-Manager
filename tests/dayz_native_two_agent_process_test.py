#!/usr/bin/env python3
"""Two real Agent handler processes, one isolated Controller DB; no game daemon.

Exercises Controller native-start bootstrap, per-Agent private filesystem,
start acknowledgement and Agent process crash/recovery without systemd or
production games. This is a process-level gate, not a two-host deployment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"database",ROOT/"agents"/"linux"/"runtime",ROOT/"agents"/"common"):
    if str(p) not in sys.path:sys.path.insert(0,str(p))


def agent_process(config):
    """Isolated Linux Agent-runtime worker in its own operating-system process."""
    import instance_runtime
    import native_restart_client
    import privileged_materialization
    record=config["record"]
    local={"agent_id":record["agent_id"]}

    # No real systemd or DLC changes: use fixture adapter while preserving
    # real Agent-owned registry, command handlers, locks, XML and history.
    state={"running":False}
    class Adapter:
        name="process-fixture"
        def status(self,record):
            return {"adapter":self.name,"available":True,
                    "active_state":"active" if state["running"] else "inactive"}
        def start(self,record):
            was=state["running"]
            state["running"]=True
            return {"changed":not was,"idempotent":was,"state":self.status(record)}
    instance_runtime.resolve_adapter=lambda record:Adapter()
    privileged_materialization.repair_dayz_dlc_ownership=lambda *args,**kwargs:None

    if instance_runtime.get_instance(record["instance_id"]) is None:
        instance_runtime.register_instance(record)

    for line in sys.stdin:
        try:
            request=json.loads(line)
            kind=request.get("op")
            if kind=="exit":
                print(json.dumps({"status":"exiting"}),flush=True)
                break
            if kind=="native":
                response=native_restart_client.handle_command(local,request["command"])
            elif kind=="instance":
                response=instance_runtime.handle_command(local,request["command"])
            elif kind=="state":
                response={"status":"ok","running":state["running"]}
            else:
                raise ValueError("unsupported Agent fixture request")
        except Exception as exc:
            response={"status":"fixture_error","error":str(exc)}
        print(json.dumps(response,sort_keys=True,default=str),flush=True)


class DayZTwoAgentProcessTest(unittest.TestCase):
    def test_separate_agent_processes_and_durable_preparation(self):
        from backend import DatabaseConfig
        from backend_factory import create_backend
        from registry import installation_profile_identity
        from registry_repository import RegistryRepository
        from agent_pairing_repository import AgentPairingRepository
        from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
        from dayz_native_restart_repository import DayZNativeRestartRepository
        from maintenance_repository import MaintenanceRepository

        with tempfile.TemporaryDirectory(prefix="dsm-dayz-2agent-") as tmp:
            root=Path(tmp)
            backend=create_backend(DatabaseConfig(
                driver="sqlite",database=str(root/"controller.db"),
            ))
            backend.initialize()
            try:
                ident=installation_profile_identity(
                    RegistryRepository(backend),profile="controller",
                    hostname="dayz-process-ci-controller",
                )
                controller=str(ident["controller_id"])
                pairing=AgentPairingRepository(backend)
                agents=("agent-process-a","agent-process-b")
                instances=("dayz-process-a","dayz-process-b")
                mission=("regular.namalsk","hardcore.namalsk")
                processes={}
                configurations={}
                try:
                    with backend.transaction() as db:
                        db.execute(
                            "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
                            (1,controller,"DayZ process fixture","active"),
                        )
                    for n,(aid,iid,map_name) in enumerate(zip(agents,instances,mission)):
                        node="node-process-"+str(n)
                        token=pairing.issue_token(controller_id=controller,created_by="test")
                        pairing.enroll(
                            pairing_token=token.token,agent_id=aid,node_id=node,
                            name=aid,fingerprint="sha256:"+aid,hostname=aid,
                            os_name="linux",architecture="x86_64",
                            address="192.0.2."+str(91+n),
                        )
                        with backend.transaction() as db:
                            db.execute("UPDATE agents SET status='active' WHERE id=?",(aid,))
                            db.execute("UPDATE nodes SET status='online' WHERE id=?",(node,))
                            db.execute(
                                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id)"
                                " VALUES(?,?,?,?,?,?,?,?)",
                                (iid,node,"dayz",iid,"offline",controller,aid,1),
                            )
                        agent_root=root/aid
                        work=agent_root/"instance"
                        active_mission=work/"mpmissions"/map_name
                        active_mission.mkdir(parents=True)
                        (work/"serverDZ.cfg").write_text(
                            'class Missions { class DayZ { template="'+map_name+'"; }; };\n',
                            encoding="utf-8",
                        )
                        record={
                            "instance_id":iid,"agent_id":aid,"game_id":"dayz",
                            "adapter":"process-fixture","working_directory":str(work),
                            "arguments":["-config=serverDZ.cfg"],
                            "observed_state":"stopped",
                        }
                        cfg={"record":record}
                        configurations[aid]=cfg
                        MaintenanceRepository(backend).set_policy(iid,{
                            "enabled":True,"schedule_mode":"interval",
                            "interval_seconds":28800,"warning_offsets_seconds":[],
                            "broadcast_enabled":False,
                        })

                    def spawn(aid):
                        env=dict(os.environ)
                        env["CAPIVARA_AGENT_STATE_DIR"]=str(root/aid/"agent-state")
                        process=subprocess.Popen(
                            [sys.executable,"-u",str(Path(__file__).resolve()),"--agent-worker",
                             json.dumps(configurations[aid])],
                            cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,text=True,bufsize=1,
                        )
                        processes[aid]=process
                        return process

                    def exchange(aid,op,command=None):
                        proc=processes[aid]
                        self.assertIsNone(proc.poll(),f"{aid} exited before {op}")
                        payload={"op":op}
                        if command is not None:payload["command"]=command
                        proc.stdin.write(json.dumps(payload)+"\n")
                        proc.stdin.flush()
                        line=proc.stdout.readline()
                        self.assertTrue(line,f"{aid} missing response for {op}")
                        result=json.loads(line)
                        self.assertNotEqual(result.get("status"),"fixture_error",result)
                        return result

                    for aid in agents:spawn(aid)
                    runtime=AgentInstanceRuntimeRepository(backend)
                    native=DayZNativeRestartRepository(backend)
                    starts={}
                    preparations={}
                    for aid,iid in zip(agents,instances):
                        starts[aid]=runtime.enqueue(
                            agent_id=aid,instance_id=iid,action="start",
                            requested_by="e2e-authorized-user",
                        )
                        self.assertIsNone(runtime.command_for_agent(aid))
                        preparations[aid]=native.command_for_agent(aid)
                        self.assertEqual(preparations[aid]["instance_id"],iid)
                        self.assertEqual(preparations[aid]["agent_id"],aid)
                        native.mark_delivered(preparations[aid]["command_id"])

                    self.assertNotEqual(
                        preparations[agents[0]]["command_id"],
                        preparations[agents[1]]["command_id"],
                    )
                    for aid in agents:
                        reply=exchange(aid,"native",preparations[aid])
                        self.assertEqual(reply["status"],"completed",reply)
                        self.assertTrue(reply["result"]["materialized"])
                        native.apply_result(aid,reply)

                    # Kill/relaunch Agent A *after* the native preparation
                    # is durably recorded but *before* the authorized start.
                    first=agents[0]
                    exchange(first,"exit")
                    processes[first].wait(timeout=5)
                    spawn(first)

                    dispatch={}
                    for aid in agents:
                        issued=runtime.command_for_agent(aid)
                        self.assertIsNotNone(issued)
                        self.assertEqual(issued["command_id"],starts[aid]["command_id"])
                        self.assertEqual(
                            issued["native_bootstrap"]["command_id"],
                            preparations[aid]["command_id"],
                        )
                        dispatch[aid]=issued
                        runtime.mark_delivered(issued["command_id"])

                    # Starting A must not start B; each isolated process
                    # validates its own local Agent preparation history.
                    first_result=exchange(agents[0],"instance",dispatch[agents[0]])
                    self.assertEqual(first_result["status"],"completed",first_result)
                    runtime.apply_result(agents[0],first_result)
                    self.assertTrue(exchange(agents[0],"state")["running"])
                    self.assertFalse(exchange(agents[1],"state")["running"])

                    second_result=exchange(agents[1],"instance",dispatch[agents[1]])
                    self.assertEqual(second_result["status"],"completed",second_result)
                    runtime.apply_result(agents[1],second_result)
                    self.assertTrue(exchange(agents[1],"state")["running"])

                    for aid,iid,map_name in zip(agents,instances,mission):
                        xml=root/aid/"instance"/"mpmissions"/map_name/"db"/"messages.xml"
                        self.assertTrue(xml.is_file(),xml)
                        self.assertIn("<shutdown>1</shutdown>",xml.read_text(encoding="utf-8"))
                        self.assertEqual(runtime.snapshot(starts[aid]["command_id"])["status"],"completed")
                        self.assertNotIn(
                            agents[1] if aid==agents[0] else agents[0],
                            xml.read_text(encoding="utf-8"),
                        )
                finally:
                    for aid,p in processes.items():
                        if p.poll() is None:
                            try:
                                p.stdin.write('{"op":"exit"}\n')
                                p.stdin.flush()
                                p.wait(timeout=5)
                            except Exception:
                                p.kill()
                                p.wait(timeout=5)
                        if p.stdin:p.stdin.close()
                        if p.stdout:p.stdout.close()
                        if p.stderr:p.stderr.close()
            finally:
                backend.close()


if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--agent-worker":
        agent_process(json.loads(sys.argv[2]))
    else:
        unittest.main()
