"""Read-only, fail-closed observation of a physical disposable NeoForge runtime."""
from __future__ import annotations
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('serverpack_observer',ROOT/'scripts/minecraft_serverpack_observe_runtime.py')
observer=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


class RuntimeObserverTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='serverpack-runtime-observer-')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'runtime'
        self.root.mkdir()
        self.version='26.1.2.109'
        canonical=self.root/'libraries/net/neoforged/neoforge'/self.version/'unix_args.txt'
        canonical.parent.mkdir(parents=True)
        canonical.write_text('--loader '+self.version+'\n')
        (self.root/'capivara-launch.args').write_bytes(canonical.read_bytes())
        (self.root/'mods').mkdir()
        self.mod=self.root/'mods/mod-a.jar'
        self.payload=b'DSM disposable mod fixture'
        self.mod.write_bytes(self.payload)
        self.bundle={'provider':'local','provider_project_id':'p','provider_version_id':'v',
            'minecraft_version':'26.1.2','loader_id':'neoforge',
            'loader_version':self.version,'manifest_kind':'serverpack-local-v1',
            'override_roots':[], 'members':[{'content_id':'mod-a',
            'path':'mods/mod-a.jar','required':True,'artifact':{
                'provider':'local','serverpack_child_v1':True,
                'ephemeral_upload':True,'bundle_parent_content_id':'pack',
                'bundle_member':'mods/mod-a.jar','serverpack_loader':'neoforge',
                'serverpack_loader_version':self.version,
                'sha256':hashlib.sha256(self.payload).hexdigest(),
                'size_bytes':len(self.payload)}}]}

    def observe(self):
        return observer.observe_runtime(self.root,instance_id='inst',
                                        content_id='pack',bundle=self.bundle)

    def test_verified_runtime_is_not_equated_with_process_boot(self):
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        status=self.observe()
        after={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(status['status'],'physical_runtime_verified')
        self.assertFalse(status['boot_verified'])
        self.assertFalse(status['ready_for_release'])
        self.assertEqual(status['reason'],'boot_not_observed')
        self.assertEqual(before,after)

    def test_modified_same_size_jar_fails(self):
        self.mod.write_bytes(b'x'*len(self.payload))
        self.assertEqual(self.observe()['reason'],'physical_manifest_mismatch')

    def test_loader_drift_fails(self):
        (self.root/'capivara-launch.args').write_text('--loader 26.1.2.94\n')
        self.assertEqual(self.observe()['reason'],'loader_mismatch')

    def test_extra_jar_fails(self):
        (self.root/'mods/extra.jar').write_bytes(b'bad')
        self.assertEqual(self.observe()['reason'],'physical_manifest_mismatch')

    def test_unknown_loader_is_refused(self):
        self.bundle['loader_id']='fabric'
        self.assertEqual(self.observe()['reason'],'invalid_loader_contract')


if __name__=='__main__':unittest.main()