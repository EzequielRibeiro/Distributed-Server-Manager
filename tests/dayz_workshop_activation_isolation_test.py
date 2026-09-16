#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(platform: str, body: str) -> subprocess.CompletedProcess[str]:
    runtime = ROOT / "agents" / platform / "runtime"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(runtime), str(ROOT / "core"), str(ROOT / "database"), str(ROOT)]
    )
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


class DayZWorkshopActivationIsolationTest(unittest.TestCase):
    def assert_ok(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")

    def test_linux_projects_modes_deduplicates_and_materializes_private_keyring(self) -> None:
        result = _run(
            "linux",
            r'''
import tempfile
from pathlib import Path
from content_activation_runtime import project_runtime_spec, materialize_content_activation
from runtime_spec import validate_runtime_spec
from materializers.systemd import render_unit

with tempfile.TemporaryDirectory() as td:
    root=Path(td);state=root/'state';work=root/'serverfiles';state.mkdir();work.mkdir();(work/'keys').mkdir()
    (work/'keys'/'dayz_base.bikey').write_bytes(b'base')
    mod_a=state/'content'/'workshop'/'111';mod_b=state/'content'/'workshop'/'222'
    (mod_a/'keys').mkdir(parents=True);(mod_b/'Keys').mkdir(parents=True)
    (mod_a/'keys'/'a.bikey').write_bytes(b'a-key');(mod_b/'Keys'/'b.bikey').write_bytes(b'b-key')
    exe=work/'DayZServer';exe.write_bytes(b'x')
    spec={'instance_id':'dayz-a','agent_id':'agent-a','game_id':'dayz','runtime_id':'dayz-a','adapter':'systemd','user':'capivara-instance','working_directory':str(work),'path':str(work),'instance_state_root':str(state),'executable':str(exe),'arguments':['-config=serverDZ.cfg'],'environment':{},'desired_state':'stopped'}
    entries=[
      {'game_id':'dayz','managed_path':str(mod_a),'activation':{'adapter':'dayz','mode':'mod'}},
      {'game_id':'dayz','managed_path':str(mod_a),'activation':{'adapter':'dayz','mode':'mod'}},
      {'game_id':'dayz','managed_path':str(mod_b),'activation':{'adapter':'dayz','mode':'server-mod'}},
    ]
    projected=project_runtime_spec(spec,{'checksum':'abc','entries':entries})
    assert projected['arguments'][0]=='-config=serverDZ.cfg'
    assert projected['arguments'].count('-mod='+str(mod_a.resolve()))==1
    assert projected['arguments'].count('-serverMod='+str(mod_b.resolve()))==1
    keyring=str((state/'.dsm/dayz-keys').resolve());target=str((work/'keys').resolve())
    assert {'source':keyring,'target':target} in projected['bind_paths']
    assert len(projected['content_dayz_key_sources'])==2
    validated=validate_runtime_spec(projected,expected_agent_id='agent-a')
    written=materialize_content_activation(validated)
    assert set(p.name for p in (state/'.dsm/dayz-keys').iterdir())=={'dayz_base.bikey','a.bikey','b.bikey'}
    assert '.dsm/dayz-keys/a.bikey' in written and '.dsm/dayz-keys/b.bikey' in written
    unit=render_unit(validated)
    assert f'BindPaths={keyring}:{target}' in unit
''',
        )
        self.assert_ok(result)

    def test_linux_fails_closed_on_conflicts_tampering_and_shared_paths(self) -> None:
        result = _run(
            "linux",
            r'''
import tempfile
from pathlib import Path
from content_activation_dayz import DayZContentActivationError,project_dayz_activation,materialize_dayz_keyring

with tempfile.TemporaryDirectory() as td:
    root=Path(td);state=root/'state';work=root/'serverfiles';state.mkdir();work.mkdir();(work/'keys').mkdir()
    a=state/'content'/'a';b=state/'content'/'b';(a/'keys').mkdir(parents=True);(b/'keys').mkdir(parents=True)
    (a/'keys'/'same.bikey').write_bytes(b'one');(b/'keys'/'same.bikey').write_bytes(b'two')
    spec={'instance_id':'dayz-a','instance_state_root':str(state),'working_directory':str(work)}
    try:project_dayz_activation(spec,[{'managed_path':str(a),'activation':{'mode':'mod'}},{'managed_path':str(b),'activation':{'mode':'mod'}}])
    except DayZContentActivationError as exc:assert 'conflicting DayZ signature key' in str(exc)
    else:raise AssertionError('conflicting key accepted')
    try:project_dayz_activation(spec,[{'managed_path':str(a),'activation':{'mode':'mod'}},{'managed_path':str(a),'activation':{'mode':'server-mod'}}])
    except DayZContentActivationError as exc:assert 'simultaneously' in str(exc)
    else:raise AssertionError('conflicting activation mode accepted')
    shared=work/'content'/'workshop'/'333';shared.mkdir(parents=True)
    try:project_dayz_activation(spec,[{'managed_path':str(shared),'activation':{'mode':'mod'}}])
    except DayZContentActivationError as exc:assert 'not instance-scoped' in str(exc)
    else:raise AssertionError('shared managed path accepted')
    (b/'keys'/'same.bikey').unlink();(b/'keys'/'b.bikey').write_bytes(b'b')
    projected=project_dayz_activation(spec,[{'managed_path':str(a),'activation':{'mode':'mod'}}])
    runtime={**spec,'content_dayz_key_sources':projected['key_sources'],'content_dayz_keyring':str(state/'.dsm/dayz-keys'),'content_dayz_base_keys_root':str(work/'keys')}
    (a/'keys'/'same.bikey').write_bytes(b'tampered')
    try:materialize_dayz_keyring(runtime)
    except DayZContentActivationError as exc:assert 'changed after discovery' in str(exc)
    else:raise AssertionError('tampered key accepted')
''',
        )
        self.assert_ok(result)

    def test_linux_content_storage_migrates_dayz_off_shared_runtime_tree(self) -> None:
        result = _run(
            "linux",
            r'''
import tempfile
from pathlib import Path
import content_client

with tempfile.TemporaryDirectory() as td:
    root=Path(td);state=root/'instance-state';work=root/'shared-serverfiles';state.mkdir();work.mkdir()
    record={'instance_id':'dayz-a','agent_id':'agent-a','game_id':'dayz','path':str(work),'instance_state_root':str(state)}
    content_client.instance_runtime.get_instance=lambda iid:dict(record)
    _,selected=content_client._owned({'agent_id':'agent-a'},{'instance_id':'dayz-a','game_id':'dayz'})
    assert selected==state.resolve()
    legacy=work/'content'/'workshop'/'111';legacy.mkdir(parents=True)
    isolated=state/'content'/'workshop'/'111';isolated.mkdir(parents=True)
    cmd={'instance_id':'dayz-a','game_id':'dayz'}
    assert not content_client._managed_path_current({'agent_id':'agent-a'},cmd,str(legacy))
    assert content_client._managed_path_current({'agent_id':'agent-a'},cmd,str(isolated))
    minecraft={**record,'game_id':'minecraft'}
    content_client.instance_runtime.get_instance=lambda iid:dict(minecraft)
    _,selected=content_client._owned({'agent_id':'agent-a'},{'instance_id':'dayz-a','game_id':'minecraft'})
    assert selected==work.resolve()
''',
        )
        self.assert_ok(result)

    def test_windows_is_instance_scoped_and_fails_closed_when_workshop_has_bikey(self) -> None:
        result = _run(
            "windows",
            r'''
import tempfile
from pathlib import Path
from content_activation_runtime import ContentRuntimeActivationError,project_runtime_spec

with tempfile.TemporaryDirectory() as td:
    root=Path(td);state=root/'state';work=root/'serverfiles';state.mkdir();work.mkdir()
    mod=state/'content'/'workshop'/'111';(mod/'keys').mkdir(parents=True);(mod/'keys'/'a.bikey').write_bytes(b'a-key')
    spec={'instance_id':'dayz-a','agent_id':'agent-a','game_id':'dayz','runtime_id':'dayz-a','working_directory':str(work),'path':str(work),'instance_state_root':str(state),'executable':str(work/'DayZServer_x64.exe'),'arguments':[],'environment':{},'desired_state':'stopped'}
    entry={'game_id':'dayz','managed_path':str(mod),'activation':{'adapter':'dayz','mode':'mod'}}
    try:project_runtime_spec(spec,{'checksum':'1','entries':[entry]})
    except ContentRuntimeActivationError as exc:assert 'cannot be isolated safely' in str(exc)
    else:raise AssertionError('Windows accepted Workshop signature key without isolation')
    (mod/'keys'/'a.bikey').unlink()
    projected=project_runtime_spec(spec,{'checksum':'2','entries':[entry]})
    assert projected['arguments']==['-mod='+str(mod.resolve())]
    shared=work/'content'/'workshop'/'111';shared.mkdir(parents=True)
    bad={**entry,'managed_path':str(shared)}
    try:project_runtime_spec(spec,{'checksum':'3','entries':[bad]})
    except ContentRuntimeActivationError as exc:assert 'not instance-scoped' in str(exc)
    else:raise AssertionError('Windows accepted shared DayZ mod path')
''',
        )
        self.assert_ok(result)

    def test_windows_content_storage_prefers_instance_state_for_dayz(self) -> None:
        result = _run(
            "windows",
            r'''
import tempfile
from pathlib import Path
import content_client

with tempfile.TemporaryDirectory() as td:
    root=Path(td);state=root/'instance-state';work=root/'shared-serverfiles';state.mkdir();work.mkdir()
    record={'instance_id':'dayz-a','agent_id':'agent-a','game_id':'dayz','path':str(work),'instance_state_root':str(state)}
    content_client.instance_runtime.get_instance=lambda iid:dict(record)
    _,selected=content_client._owned({'agent_id':'agent-a'},{'instance_id':'dayz-a','game_id':'dayz'})
    assert selected==state.resolve()
    legacy=work/'content'/'workshop'/'111';legacy.mkdir(parents=True)
    isolated=state/'content'/'workshop'/'111';isolated.mkdir(parents=True)
    cmd={'instance_id':'dayz-a','game_id':'dayz'}
    assert not content_client._managed_path_current({'agent_id':'agent-a'},cmd,str(legacy))
    assert content_client._managed_path_current({'agent_id':'agent-a'},cmd,str(isolated))
''',
        )
        self.assert_ok(result)


if __name__ == "__main__":
    unittest.main()
