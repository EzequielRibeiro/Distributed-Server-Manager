import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'database'))
from instance_evidence_migration import migrate_postgresql,NAME,CHECKSUM

class DictRowMigrationTest(unittest.TestCase):
    def test_valid_dict_row_is_idempotent(self):
        db=MagicMock()
        db.execute.return_value.fetchone.side_effect=[{'name':NAME,'checksum':CHECKSUM},{'?column?':1}]
        self.assertFalse(migrate_postgresql(db))
        self.assertFalse(any('ALTER TABLE' in call.args[0] for call in db.execute.call_args_list))

    def test_invalid_dict_checksum_is_rejected(self):
        db=MagicMock()
        db.execute.return_value.fetchone.return_value={'name':NAME,'checksum':'bad'}
        with self.assertRaises(RuntimeError):migrate_postgresql(db)

if __name__=='__main__':unittest.main()
