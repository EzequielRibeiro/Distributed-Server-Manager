#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"database",ROOT/"core"):
    if str(path) not in sys.path:
        sys.path.insert(0,str(path))

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from content_repository import ContentRepository
from core.minecraft_serverpack_pending_commit import build_pending_bundle_commit


def local_artifact(content_id:str,version:str,sha_char:str):
    return {
        "provider":"local",
        "serverpack_child_v1":True,
        "ephemeral_upload":True,
        "bundle_parent_content_id":"atm11",
        "bundle_member":f"mods/{content_id}.jar",
        "serverpack_loader":"neoforge",
        "serverpack_loader_version":version,
        "sha256":sha_char*64,
        "size_bytes":123,
    }


def bundle(version_id:str,loader_version:str,sha_char:str):
    artifact=local_artifact("mod-a",loader_version,sha_char)
    return {
        "provider":"local",
        "provider_project_id":"cf-1148445",
        "provider_version_id":version_id,
        "minecraft_version":"26.1.2",
        "loader_id":"neoforge",
        "loader_version":loader_version,
        "manifest_kind":"serverpack-local-v1",
        "members":[{"content_id":"mod-a","path":"mods/mod-a.jar","required":True,"artifact":artifact}],
        "override_roots":["server-overrides"],
    }


def parent(version_id:str):
    return {
        "instance_id":"pr855-controller-atomic",
        "content_id":"atm11",
        "content_type":"modpack",
        "provider":"local",
        "version":version_id,
        "target":"modpacks/atm11",
        "artifact":{
            "provider":"local","package_id":f"quarantine/{version_id}.zip",
            "filename":f"{version_id}.zip","archive":True,"ephemeral_upload":True,
        },
        "metadata":{},
    }


def child(version_id:str,loader_version:str,sha_char:str):
    return {
        "instance_id":"pr855-controller-atomic",
        "content_id":"mod-a",
        "content_type":"mod",
        "provider":"local",
        "version":version_id,
        "target":"mods/mod-a",
        "artifact":local_artifact("mod-a",loader_version,sha_char),
        "metadata":{},
    }


def isolated_linux_provisioning_modules():
    """Load Linux state/client together regardless of prior Windows test imports."""
    import importlib.util
    from unittest.mock import patch
    runtime=ROOT/"agents/linux/runtime"
    state_spec=importlib.util.spec_from_file_location("pr855_isolated_linux_provisioning_state",runtime/"provisioning_state.py")
    state=importlib.util.module_from_spec(state_spec)
    state_spec.loader.exec_module(state)
    with patch.dict(sys.modules,{"provisioning_state":state}):
        client_spec=importlib.util.spec_from_file_location("pr855_isolated_linux_provisioning_client",runtime/"provisioning_client.py")
        client=importlib.util.module_from_spec(client_spec)
        client_spec.loader.exec_module(client)
    return state,client


class AtomicPendingPublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="pr855-controller-atomic-")
        self.backend=create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(Path(self.temp.name)/"db.sqlite"),
        ))
        self.backend.initialize()
        with self.backend.transaction() as c:
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("ctrl-node","Controller","controller"))
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("agent-node","Agent","agent"))
            c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("ctrl","ctrl-node","Controller"))
            c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("pr839-isolated-agent","ctrl","agent-node","Agent","active"))
            customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("ctrl","Customer"))
            c.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id,game_version,build_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("pr855-controller-atomic","agent-node","minecraft","minecraft.java.neoforge","Lab","stopped","ctrl","pr839-isolated-agent",customer.lastrowid,"26.1.2","26.1.2.94"),
            )
            c.execute(
                "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
                ("pr855-controller-atomic","agent-node","game","tcp",25582),
            )
        self.content=ContentRepository(self.backend)
        self.content.initialize()
        first=self.content.put_bundle(
            parent("old"),
            bundle("old","26.1.2.94","a"),
            [child("old","26.1.2.94","a")],
            requested_by="customer",
        )
        self.assertEqual(first["bundle_revision"],1)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def pending(self,fingerprint="c"*64):
        new_bundle=bundle("new","26.1.2.109","b")
        new_parent=parent("new")
        new_child=child("new","26.1.2.109","b")
        return build_pending_bundle_commit(
            instance_id="pr855-controller-atomic",
            content_id="atm11",
            transfer_id="transfer-atomic",
            migration_plan_sha256=fingerprint,
            expected_previous_revision=1,
            parent=new_parent,
            bundle=new_bundle,
            children=[new_child],
            requested_by="customer",
        )

    def enqueue(self,pending,*,production=False):
        repo=AgentInstanceProvisioningRepository(self.backend)
        state=repo.enqueue(
            agent_id="pr839-isolated-agent",
            instance_id="pr855-controller-atomic",
            environment_id="minecraft.java.neoforge",
            selector="26.1.2@26.1.2.109",
            selection={"runtime_definition":"minecraft.java.neoforge","version":"26.1.2","build":"26.1.2.109"},
            configuration={
                "minecraft_serverpack_migration":{
                    "kind":"MinecraftServerPackMigration",
                    "instance_id":"pr855-controller-atomic",
                },
                "minecraft_serverpack_pending_bundle":pending,
                **({"minecraft_serverpack_execution_mode":"production"} if production else {}),
            },
            desired_state="stopped",
            requested_by="customer",
        )
        return repo,state

    def completed(self,state,pending,*,fingerprint=None):
        fp=fingerprint or pending["migration_plan_sha256"]
        return {
            "provisioning_id":state["provisioning_id"],
            "instance_id":"pr855-controller-atomic",
            "status":"completed",
            "progress":100,
            "current_step":"completed",
            "minecraft_serverpack_migration":{
                "status":"completed",
                "instance_id":"pr855-controller-atomic",
                "content_id":"atm11",
                "transfer_id":"transfer-atomic",
                "migration_plan_sha256":fp,
                "from_loader_version":"26.1.2.94",
                "target_loader_version":"26.1.2.109",
                "commit":{
                    "status":"committed",
                    "journal":{
                        "phase":"committed",
                        "migration_plan_sha256":fp,
                    },
                },
            },
        }

    def test_real_jar_bytes_bind_agent_attestation_to_controller_publication(self):
        """Use real temporary bytes, the Agent verifier and the SQLite CAS path."""
        import hashlib
        from minecraft_serverpack_physical_manifest import (
            MinecraftServerPackPhysicalManifestError, attest_serverpack_mods,
        )
        from core.content_bundle import normalize_bundle

        runtime=Path(self.temp.name)/"candidate-runtime"
        mods=runtime/"mods"
        mods.mkdir(parents=True)
        jar=mods/"mod-a.jar"
        payload=b"DSM PR1013 disposable NeoForge mod fixture"
        sha=hashlib.sha256(payload).hexdigest()
        jar.write_bytes(b"x"*len(payload))

        target=bundle("new","26.1.2.109","b")
        artifact={**target["members"][0]["artifact"],
                  "sha256":sha,"size_bytes":len(payload)}
        target["members"][0]["artifact"]=artifact
        member=child("new","26.1.2.109","b")
        member["artifact"]=dict(artifact)
        pending=build_pending_bundle_commit(
            instance_id="pr855-controller-atomic",content_id="atm11",
            transfer_id="transfer-atomic",migration_plan_sha256="c"*64,
            expected_previous_revision=1,parent=parent("new"),
            bundle=target,children=[member],requested_by="customer")
        repo,state=self.enqueue(pending,production=True)
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError,
                                    "SHA-256"):
            attest_serverpack_mods(runtime,instance_id=pending["instance_id"],
                                   content_id=pending["content_id"],
                                   bundle=pending["bundle"])
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],1)
        jar.write_bytes(payload)
        proof=attest_serverpack_mods(runtime,instance_id=pending["instance_id"],
                                    content_id=pending["content_id"],
                                    bundle=pending["bundle"])
        canonical=normalize_bundle({**pending["bundle"],
            "instance_id":pending["instance_id"],
            "parent_content_id":pending["content_id"]})
        self.assertEqual(proof["manifest_sha256"],canonical["manifest_sha256"])
        self.assertEqual(proof["mod_count"],1)
        result=self.completed(state,pending)
        result["minecraft_serverpack_migration"]["physical_manifest"]=proof
        applied=repo.apply_result("pr839-isolated-agent",result)
        self.assertEqual(applied["status"],"completed")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],2)
        self.assertEqual(applied["result"]["controller_bundle_publication"]["manifest_sha256"],
                         proof["manifest_sha256"])
        replay=repo.apply_result("pr839-isolated-agent",result)
        self.assertEqual(replay["status"],"completed")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],2)

    def test_production_publication_needs_matching_physical_jars_attestation(self):
        from core.content_bundle import normalize_bundle
        pending=self.pending()
        canonical=normalize_bundle({**pending["bundle"],
            "instance_id":pending["instance_id"],
            "parent_content_id":pending["content_id"]})
        repo,state=self.enqueue(pending,production=True)
        proof={"status":"physical_mods_verified",
               "manifest_sha256":canonical["manifest_sha256"],
               "mod_count":len(canonical["manifest"]["members"])}
        for bad in (None,{},
                    {**proof,"manifest_sha256":"f"*64},
                    {**proof,"mod_count":0},
                    {**proof,"status":"unverified"}):
            with self.subTest(proof=bad):
                result=self.completed(state,pending)
                if bad is not None:
                    result["minecraft_serverpack_migration"]["physical_manifest"]=bad
                with self.assertRaisesRegex(Exception,"requires matching Agent physical JAR attestation"):
                    repo.apply_result("pr839-isolated-agent",result)
                self.assertEqual(repo.snapshot(state["provisioning_id"])["status"],"queued")
                self.assertEqual(self.content.bundle_history(
                    "pr855-controller-atomic","atm11")[0]["revision"],1)
        result=self.completed(state,pending)
        result["minecraft_serverpack_migration"]["physical_manifest"]=proof
        completed=repo.apply_result("pr839-isolated-agent",result)
        self.assertEqual(completed["status"],"completed")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],2)

    def test_completed_agent_result_publishes_bundle_in_same_completion_transaction(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        self.assertEqual(self.content.bundle_history("pr855-controller-atomic","atm11")[0]["revision"],1)
        completed=repo.apply_result(
            "pr839-isolated-agent",
            self.completed(state,pending),
        )
        self.assertEqual(completed["status"],"completed")
        history=self.content.bundle_history("pr855-controller-atomic","atm11")
        self.assertEqual(history[0]["revision"],2)
        self.assertEqual(history[0]["loader_version"],"26.1.2.109")
        publication=completed["result"]["controller_bundle_publication"]
        self.assertEqual(publication["status"],"published")
        self.assertEqual(publication["previous_bundle_revision"],1)
        self.assertEqual(publication["bundle_revision"],2)
        self.assertTrue(publication["instance_runtime_updated"])
        self.assertEqual(publication["from_loader_version"],"26.1.2.94")
        self.assertEqual(publication["target_loader_version"],"26.1.2.109")
        with self.backend.connect() as connection:
            row=connection.execute(
                "SELECT game_version,build_id FROM instances WHERE id=?",
                ("pr855-controller-atomic",),
            ).fetchone()
        self.assertEqual(row["game_version"],"26.1.2")
        self.assertEqual(row["build_id"],"26.1.2.109")

    def test_interrupted_finalization_stays_running_until_replayed_completion(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        first=self.completed(state,pending)
        first.update({
            "status":"running",
            "progress":99,
            "current_step":"minecraft_serverpack_finalization",
            "finalization_state":"pending",
        })
        first["minecraft_serverpack_migration"].update({
            "status":"finalization_pending",
            "trace":["committed","finalization_pending"],
        })
        running=repo.apply_result("pr839-isolated-agent",first)
        self.assertEqual(running["status"],"running")
        self.assertEqual(running["progress"],99)
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],1)
        with self.backend.connect() as connection:
            row=connection.execute("SELECT build_id FROM instances WHERE id=?",
                                   ("pr855-controller-atomic",)).fetchone()
        self.assertEqual(row["build_id"],"26.1.2.94")
        final=self.completed(state,pending)
        final["minecraft_serverpack_migration"].update({
            "trace":["committed","finalized"],
            "finalization":{
                "status":"archived","sha256":"e"*64,
                "observed_state":"stopped",
            },
        })
        completed=repo.apply_result("pr839-isolated-agent",final)
        self.assertEqual(completed["status"],"completed")
        self.assertEqual(completed["progress"],100)
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],2)
        repeated=repo.apply_result("pr839-isolated-agent",final)
        self.assertEqual(repeated["status"],"completed")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],2)
        self.assertEqual(
            repeated["result"]["controller_bundle_publication"]["bundle_revision"],2)

    def test_completed_envelope_cannot_override_pending_finalization_evidence(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        result=self.completed(state,pending)
        result["minecraft_serverpack_migration"].update({
            "status":"finalization_pending",
            "trace":["committed","finalization_pending"],
        })
        with self.assertRaisesRegex(ValueError,"still pending"):
            repo.apply_result("pr839-isolated-agent",result)
        snapshot=repo.snapshot(state["provisioning_id"])
        self.assertEqual(snapshot["status"],"queued")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],1)

    def test_restart_pending_envelope_never_commits_bundle(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        result=self.completed(state,pending)
        result["minecraft_serverpack_migration"].update({
            "status":"restart_pending",
            "finalization":{"status":"restart_pending"},
        })
        with self.assertRaisesRegex(ValueError,"still pending"):
            repo.apply_result("pr839-isolated-agent",result)
        self.assertEqual(repo.snapshot(state["provisioning_id"])["status"],"queued")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],1)

    def test_duplicate_running_heartbeat_after_completion_cannot_regress_state(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        final=self.completed(state,pending)
        final["minecraft_serverpack_migration"].update({
            "trace":["committed","finalized"],
            "finalization":{"status":"archived","sha256":"e"*64},
        })
        repo.apply_result("pr839-isolated-agent",final)
        late=self.completed(state,pending)
        late.update({
            "status":"running","progress":99,
            "current_step":"minecraft_serverpack_finalization",
            "finalization_state":"pending",
        })
        late["minecraft_serverpack_migration"]["status"]="finalization_pending"
        result=repo.apply_result("pr839-isolated-agent",late)
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["progress"],100)
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],2)

    def test_agent_file_to_controller_terminal_ack_and_replay(self):
        """Verify persisted Agent result, SQLite publication and ACK archival."""
        from unittest.mock import patch
        agent_state,client=isolated_linux_provisioning_modules()
        pending=self.pending()
        repo,state=self.enqueue(pending)
        pid=state["provisioning_id"]
        store=Path(self.temp.name)/"agent-state"/"instance-provisioning"
        store.mkdir(parents=True)
        history=store/"history"
        with patch.object(agent_state,"PROVISION_ROOT",store), \
             patch.object(agent_state,"HISTORY_ROOT",history), \
             patch.object(client,"PROVISION_ROOT",store):
            _,result_file,_=agent_state.paths(pid)
            running=self.completed(state,pending)
            running.update(status="running",progress=99,
                           current_step="minecraft_serverpack_finalization",
                           finalization_state="pending")
            running["minecraft_serverpack_migration"].update(
                status="finalization_pending",
                trace=["committed","finalization_pending"])
            agent_state.write_json(result_file,running)
            latest=client.read_provisioning_result()
            self.assertEqual(latest["status"],"running")
            observed=repo.apply_result("pr839-isolated-agent",latest)
            self.assertEqual(observed["status"],"running")
            self.assertEqual(observed["progress"],99)
            self.assertTrue(result_file.exists())
            self.assertEqual(self.content.bundle_history(
                "pr855-controller-atomic","atm11")[0]["revision"],1)
            final=self.completed(state,pending)
            final["minecraft_serverpack_migration"].update(
                trace=["committed","finalized"],
                finalization={"status":"archived","sha256":"e"*64})
            agent_state.write_json(result_file,final)
            received=client.read_provisioning_result()
            accepted=repo.apply_result("pr839-isolated-agent",received)
            self.assertEqual(accepted["status"],"completed")
            self.assertEqual(self.content.bundle_history(
                "pr855-controller-atomic","atm11")[0]["revision"],2)
            repeated=repo.apply_result("pr839-isolated-agent",
                                       client.read_provisioning_result())
            self.assertEqual(repeated["status"],"completed")
            self.assertEqual(self.content.bundle_history(
                "pr855-controller-atomic","atm11")[0]["revision"],2)
            client.clear_provisioning_result(pid)
            self.assertIsNone(client.read_provisioning_result())
            self.assertFalse(result_file.exists())
            self.assertEqual(agent_state.read_json(
                history/result_file.name)["status"],"completed")

    def test_separate_agent_process_replays_controller_outage_and_archives_ack(self):
        """Exercise disk-backed Agent retries across fresh OS processes."""
        import json
        import os
        import subprocess
        from unittest.mock import patch
        import agent_instance_provisioning_repository as controller
        runtime=ROOT/"agents/linux/runtime"
        pending=self.pending()
        repo,state=self.enqueue(pending)
        pid=state["provisioning_id"]
        agent_root=Path(self.temp.name)/"separate-agent"
        results=agent_root/"instance-provisioning"
        results.mkdir(parents=True)
        result_file=results/f"{pid}.result.json"
        payload=self.completed(state,pending)
        payload["minecraft_serverpack_migration"].update(
            trace=["committed","finalized"],
            finalization={"status":"archived","sha256":"e"*64},
        )
        result_file.write_text(json.dumps(payload),encoding="utf-8")
        env={**os.environ,"CAPIVARA_AGENT_STATE_DIR":str(agent_root),
             "PYTHONPATH":str(runtime),"PYTHONDONTWRITEBYTECODE":"1"}
        def agent_process(clear=False):
            code=("import json,provisioning_client as pc; "
                  "v=pc.read_provisioning_result(); "
                  + (f"pc.clear_provisioning_result({pid!r}); " if clear else "")
                  + "print(json.dumps(v))")
            process=subprocess.run([sys.executable,"-c",code],env=env,
                                   capture_output=True,text=True,timeout=12)
            self.assertEqual(process.returncode,0,process.stderr)
            return json.loads(process.stdout.strip())
        with patch.object(controller,"publish_pending_serverpack_bundle",
                          side_effect=ConnectionError("Controller unavailable")):
            with self.assertRaisesRegex(ConnectionError,"Controller unavailable"):
                repo.apply_result("pr839-isolated-agent",agent_process())
        self.assertTrue(result_file.exists())
        self.assertEqual(repo.snapshot(pid)["status"],"queued")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],1)
        accepted=repo.apply_result("pr839-isolated-agent",agent_process())
        self.assertEqual(accepted["status"],"completed")
        repeated=repo.apply_result("pr839-isolated-agent",agent_process())
        self.assertEqual(repeated["status"],"completed")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],2)
        self.assertEqual(agent_process(clear=True)["status"],"completed")
        self.assertFalse(result_file.exists())
        archived=results/"history"/result_file.name
        self.assertEqual(json.loads(archived.read_text())["status"],"completed")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],2)

    def test_agent_ack_archive_failure_retains_replayable_terminal_result(self):
        from unittest.mock import patch
        agent_state,client=isolated_linux_provisioning_modules()
        pending=self.pending()
        repo,state=self.enqueue(pending)
        pid=state["provisioning_id"]
        store=Path(self.temp.name)/"ack-failure"/"instance-provisioning"
        store.mkdir(parents=True)
        history=store/"history"
        with patch.object(agent_state,"PROVISION_ROOT",store), \
             patch.object(agent_state,"HISTORY_ROOT",history), \
             patch.object(client,"PROVISION_ROOT",store):
            _,result_file,_=agent_state.paths(pid)
            completed=self.completed(state,pending)
            completed["minecraft_serverpack_migration"].update(
                trace=["committed","finalized"],
                finalization={"status":"archived","sha256":"e"*64},
            )
            agent_state.write_json(result_file,completed)
            accepted=repo.apply_result("pr839-isolated-agent",client.read_provisioning_result())
            self.assertEqual(accepted["status"],"completed")
            original_replace=agent_state.os.replace
            def deny_result_archive(source,destination):
                if Path(source)==result_file:
                    raise OSError("simulated history disk error")
                return original_replace(source,destination)
            with patch.object(agent_state.os,"replace",side_effect=deny_result_archive):
                with self.assertRaisesRegex(OSError,"simulated history disk error"):
                    client.clear_provisioning_result(pid)
            self.assertTrue(result_file.is_file())
            self.assertEqual(client.read_provisioning_result()["status"],"completed")
            self.assertEqual(self.content.bundle_history(
                "pr855-controller-atomic","atm11")[0]["revision"],2)
            client.clear_provisioning_result(pid)
            self.assertFalse(result_file.exists())
            self.assertEqual(agent_state.read_json(history/result_file.name)["status"],"completed")
            self.assertEqual(self.content.bundle_history(
                "pr855-controller-atomic","atm11")[0]["revision"],2)

    def test_transient_controller_publication_failure_replays_once(self):
        """Agent completion survives a simulated Controller publication outage."""
        from unittest.mock import patch
        import agent_instance_provisioning_repository as controller
        pending=self.pending()
        repo,state=self.enqueue(pending)
        completed=self.completed(state,pending)
        completed["minecraft_serverpack_migration"].update(
            trace=["committed","finalized"],
            finalization={"status":"archived","sha256":"e"*64},
        )
        # Simulate a network/backend error after Agent commitment, but before
        # the Controller's transactional publication can be acknowledged.
        with patch.object(controller,"publish_pending_serverpack_bundle",
                          side_effect=ConnectionError("simulated Controller outage")):
            with self.assertRaisesRegex(ConnectionError,"simulated Controller outage"):
                repo.apply_result("pr839-isolated-agent",completed)
        self.assertEqual(repo.snapshot(state["provisioning_id"])["status"],"queued")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],1)
        self.assertEqual(self.content.get("pr855-controller-atomic","atm11")["version"],"old")
        # The identical persisted Agent result can be sent again after the
        # Controller becomes available; neither commit nor ACK is duplicated.
        published=repo.apply_result("pr839-isolated-agent",completed)
        self.assertEqual(published["status"],"completed")
        self.assertEqual(published["result"]["controller_bundle_publication"]["bundle_revision"],2)
        replay=repo.apply_result("pr839-isolated-agent",completed)
        self.assertEqual(replay["status"],"completed")
        self.assertEqual(self.content.bundle_history(
            "pr855-controller-atomic","atm11")[0]["revision"],2)
        self.assertEqual(self.content.get("pr855-controller-atomic","atm11")["version"],"new")

    def test_mismatched_agent_fingerprint_rolls_back_job_completion_and_bundle_publication(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        with self.assertRaisesRegex(Exception,"migration_plan_sha256 mismatch"):
            repo.apply_result(
                "pr839-isolated-agent",
                self.completed(state,pending,fingerprint="d"*64),
            )
        snapshot=repo.snapshot(state["provisioning_id"])
        self.assertEqual(snapshot["status"],"queued")
        history=self.content.bundle_history("pr855-controller-atomic","atm11")
        self.assertEqual(history[0]["revision"],1)
        self.assertEqual(history[0]["loader_version"],"26.1.2.94")

    def test_stale_instance_build_rolls_back_job_completion_and_bundle_publication(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE instances SET build_id=? WHERE id=?",
                ("26.1.2.95","pr855-controller-atomic"),
            )
        with self.assertRaisesRegex(Exception,"instance runtime identity changed"):
            repo.apply_result(
                "pr839-isolated-agent",
                self.completed(state,pending),
            )
        self.assertEqual(repo.snapshot(state["provisioning_id"])["status"],"queued")
        history=self.content.bundle_history("pr855-controller-atomic","atm11")
        self.assertEqual(history[0]["revision"],1)
        self.assertEqual(history[0]["loader_version"],"26.1.2.94")
        with self.backend.connect() as connection:
            row=connection.execute(
                "SELECT build_id FROM instances WHERE id=?",
                ("pr855-controller-atomic",),
            ).fetchone()
        self.assertEqual(row["build_id"],"26.1.2.95")

    def test_bundle_session_rejects_stale_expected_revision_without_writes(self):
        from alert_repository import AlertSession
        with self.assertRaisesRegex(Exception, "revision changed"):
            with self.backend.transaction() as connection:
                session=AlertSession(self.backend,connection)
                self.content.put_bundle_session(
                    session,parent("new"),bundle("new","26.1.2.109","b"),
                    [child("new","26.1.2.109","b")],requested_by="customer",
                    expected_previous_revision=999,
                )
        self.assertEqual(self.content.bundle_history("pr855-controller-atomic","atm11")[0]["revision"],1)
        self.assertEqual(self.content.get("pr855-controller-atomic","atm11")["version"],"old")

    def test_bundle_session_cas_failure_rolls_back_partial_assignments(self):
        from alert_repository import AlertSession
        from unittest.mock import patch
        from types import SimpleNamespace
        original=AlertSession.execute
        def emulate_revision_race(session,sql,parameters=()):
            if sql.startswith("UPDATE content_bundles SET"):
                return SimpleNamespace(rowcount=0)
            return original(session,sql,parameters)
        with patch.object(AlertSession,"execute",emulate_revision_race):
            with self.assertRaisesRegex(Exception, "revision changed"):
                with self.backend.transaction() as connection:
                    session=AlertSession(self.backend,connection)
                    self.content.put_bundle_session(
                        session,parent("new"),bundle("new","26.1.2.109","b"),
                        [child("new","26.1.2.109","b")],requested_by="customer",
                        expected_previous_revision=1,
                    )
        self.assertEqual(self.content.bundle_history("pr855-controller-atomic","atm11")[0]["revision"],1)
        self.assertEqual(self.content.get("pr855-controller-atomic","atm11")["version"],"old")
        self.assertEqual(self.content.get("pr855-controller-atomic","mod-a")["version"],"old")

    def test_agent_preflight_validates_actual_pending_manifest_identity(self):
        runtime=ROOT/"agents/linux/runtime"
        if str(runtime) not in sys.path:
            sys.path.insert(0,str(runtime))
        from minecraft_serverpack_migration_provisioning import (
            _verify_pending_manifest_matches_migration,
            MinecraftServerPackProvisioningHomologationError,
        )
        pending=self.pending()
        migration={"target_loader_version":"26.1.2.109",
                   "minecraft_version":"26.1.2","serverpack_mod_count":1}
        _verify_pending_manifest_matches_migration(pending,migration)
        for override in ({"target_loader_version":"26.1.2.111"},
                         {"minecraft_version":"26.1.3"},
                         {"serverpack_mod_count":2}):
            with self.subTest(override=override):
                with self.assertRaisesRegex(MinecraftServerPackProvisioningHomologationError,
                                            "differs from migration evidence"):
                    _verify_pending_manifest_matches_migration(pending,{**migration,**override})

    def test_agent_preflight_rejects_pending_child_artifact_drift(self):
        runtime=ROOT/"agents/linux/runtime"
        if str(runtime) not in sys.path:
            sys.path.insert(0,str(runtime))
        from minecraft_serverpack_migration_provisioning import (
            _verify_pending_manifest_matches_migration,
            MinecraftServerPackProvisioningHomologationError,
        )
        pending=self.pending()
        pending["children"][0]["artifact"]={**pending["children"][0]["artifact"],"sha256":"f"*64}
        with self.assertRaisesRegex(MinecraftServerPackProvisioningHomologationError,
                                    "differs from migration evidence"):
            _verify_pending_manifest_matches_migration(pending,{
                "target_loader_version":"26.1.2.109",
                "minecraft_version":"26.1.2","serverpack_mod_count":1})

    def test_serverpack_projection_uses_committed_manifest_not_only_count(self):
        view=self.content.customer_view("pr855-controller-atomic")
        self.assertEqual(len(view),1)
        self.assertEqual(view[0]["bundle_summary"]["manifest_alignment"],"metadata_aligned")
        child_item=self.content.get("pr855-controller-atomic","mod-a")
        keys=("instance_id","content_id","content_type","desired_state","activation_state",
              "activation_order","version","provider","target","artifact","provenance",
              "metadata","dependencies","conflicts")
        modified={key:child_item.get(key) for key in keys}
        metadata=dict(modified["metadata"])
        metadata["bundle"]={**metadata["bundle"],"manifest_sha256":"f"*64}
        modified["metadata"]=metadata
        self.content.put(modified,requested_by="test")
        view=self.content.customer_view("pr855-controller-atomic")
        self.assertEqual(view[0]["bundle_summary"]["manifest_alignment"],"drift")

    def test_serverpack_projection_handles_missing_revision_as_drift(self):
        with self.backend.transaction() as connection:
            connection.execute(
                "DELETE FROM content_bundle_revisions WHERE bundle_id IN "
                "(SELECT bundle_id FROM content_bundles WHERE instance_id=? "
                "AND parent_content_id=?)",
                ("pr855-controller-atomic","atm11"),
            )
        view=self.content.customer_view("pr855-controller-atomic")
        self.assertEqual(view[0]["bundle_summary"]["manifest_alignment"],"drift")

    def test_serverpack_projection_detects_missing_member(self):
        self.assertEqual(self.content.customer_view("pr855-controller-atomic")[0]["bundle_summary"]["manifest_alignment"],"metadata_aligned")
        original=self.content.list
        self.content.list=lambda **kw:[row for row in original(**kw) if row["content_id"]!="mod-a"]
        try:
            view=self.content.customer_view("pr855-controller-atomic")
            self.assertEqual(view[0]["bundle_summary"]["manifest_alignment"],"drift")
        finally:self.content.list=original

    def test_stale_bundle_revision_rolls_back_job_completion(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        self.content.put_bundle(
            parent("other"),
            bundle("other","26.1.2.94","e"),
            [child("other","26.1.2.94","e")],
            requested_by="other",
        )
        self.assertEqual(self.content.bundle_history("pr855-controller-atomic","atm11")[0]["revision"],2)
        with self.assertRaisesRegex(Exception,"revision changed"):
            repo.apply_result(
                "pr839-isolated-agent",
                self.completed(state,pending),
            )
        self.assertEqual(repo.snapshot(state["provisioning_id"])["status"],"queued")
        self.assertEqual(self.content.bundle_history("pr855-controller-atomic","atm11")[0]["revision"],2)


if __name__=="__main__":
    unittest.main()
