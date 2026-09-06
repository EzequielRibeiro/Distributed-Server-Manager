import json
from pathlib import Path
import shutil
import tempfile
import unittest

from core.catalog_index import CatalogIndex, DEFAULT_ROOT


class CatalogIndexTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(DEFAULT_ROOT / 'games', self.root / 'games')

    def test_all_published_contracts_are_preserved(self):
        index = CatalogIndex(self.root)
        leaves = []
        for game in index.hierarchy()['games']:
            for edition in game['editions']:
                for distribution in edition['distributions']:
                    for rid in distribution['runtime_definitions']:
                        runtime = index.runtime(rid)
                        self.assertEqual((runtime['game'], runtime['edition'], runtime['variant']),
                                         (game['id'], edition['id'], distribution['id']))
                        leaves.append(rid)
        files = list((self.root / 'games').glob('*/runtimes/*.json'))
        self.assertEqual(len(leaves), len(files))
        for path in files:
            original = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(index.runtime(original['id']), original)
        self.assertIn('minecraft.java.forge', leaves)
        luanti = index.runtime('luanti.stable')
        self.assertEqual(luanti['version']['value'], '5.17.0')
        self.assertEqual(luanti['installation']['installer']['type'], 'cmake_source')

    def test_missing_or_invalid_game_fails(self):
        path = self.root / 'games/luanti/game.json'
        path.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Invalid GameDefinition'):
            CatalogIndex(self.root)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'matching GameDefinition'):
            CatalogIndex(self.root)

    def test_duplicate_and_misplaced_runtime_fail(self):
        source = self.root / 'games/luanti/runtimes/stable.json'
        target = source.with_name('duplicate.json')
        shutil.copyfile(source, target)
        with self.assertRaisesRegex(ValueError, 'Duplicate runtime'):
            CatalogIndex(self.root)
        target.unlink()
        shutil.copyfile(source, self.root / 'games/minecraft/runtimes/misplaced.json')
        with self.assertRaisesRegex(ValueError, 'matching GameDefinition'):
            CatalogIndex(self.root)

    def test_deferred_excluded_and_multiple_runtime_leaves(self):
        path = self.root / 'games/luanti/runtimes/stable.json'
        runtime = json.loads(path.read_text(encoding='utf-8'))
        runtime['id'] = 'luanti.alternate'
        path.with_name('alternate.json').write_text(json.dumps(runtime), encoding='utf-8')
        deferred = self.root / 'games/luanti/deferred'
        deferred.mkdir(exist_ok=True)
        (deferred / 'invalid.json').write_text('{}', encoding='utf-8')
        index = CatalogIndex(self.root)
        leaves = index.hierarchy('luanti')['games'][0]['editions'][0]['distributions'][0]['runtime_definitions']
        self.assertEqual(leaves, ['luanti.alternate', 'luanti.stable'])

    def test_unknown_ids_and_copy_isolation(self):
        index = CatalogIndex(self.root)
        with self.assertRaises(KeyError):
            index.hierarchy('../unknown')
        with self.assertRaises(KeyError):
            index.runtime('unknown')
        tree = index.hierarchy()
        tree['games'].clear()
        runtime = index.runtime('luanti.stable')
        runtime['version']['value'] = 'changed'
        self.assertTrue(index.hierarchy()['games'])
        self.assertEqual(index.runtime('luanti.stable')['version']['value'], '5.17.0')

    def test_game_schema(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((DEFAULT_ROOT / 'schemas/game-definition.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        for path in (self.root / 'games').glob('*/game.json'):
            validator.validate(json.loads(path.read_text(encoding='utf-8')))


if __name__ == '__main__':
    unittest.main()
