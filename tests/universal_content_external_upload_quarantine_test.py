#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,io,os,tarfile,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def _load(path:Path,name:str):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class ExternalUploadQuarantineTest(unittest.TestCase):
 def _module(self,platform,tmp):
  if platform=="linux":os.environ["CAPIVARA_GAME_DATA_ROOT"]=str(Path(tmp)/"game-data")
  else:
   os.environ["PROGRAMDATA"]=str(Path(tmp)/"programdata");os.environ["CAPIVARA_AGENT_GAME_DATA_ROOT"]=str(Path(tmp)/"game-data")
  return _load(ROOT/f"agents/{platform}/runtime/content_upload_quarantine.py",f"quarantine_{platform}_{id(self)}")
 def test_safe_zip_is_confined_and_validated_on_both_agents(self):
  for platform in ("linux","windows"):
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as tmp:
    module=self._module(platform,tmp);dest=module.quarantine_destination("transfer-abc","mods.zip");dest.parent.mkdir(parents=True)
    with zipfile.ZipFile(dest,"w") as archive:archive.writestr("mod/data.txt","ok")
    result=module.validate_quarantine_archive(dest);self.assertEqual(result["archive_type"],"zip");self.assertEqual(result["entries"],1);self.assertEqual(module.quarantine_relative_path(dest),"quarantine/transfer-abc/mods.zip")
 def test_archive_path_traversal_fails_closed(self):
  for platform in ("linux","windows"):
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as tmp:
    module=self._module(platform,tmp);dest=module.quarantine_destination("transfer-abc","bad.zip");dest.parent.mkdir(parents=True)
    with zipfile.ZipFile(dest,"w") as archive:archive.writestr("../escape.txt","nope")
    with self.assertRaises(ValueError):module.validate_quarantine_archive(dest)
 def test_tar_symlink_fails_closed(self):
  for platform in ("linux","windows"):
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as tmp:
    module=self._module(platform,tmp);dest=module.quarantine_destination("transfer-abc","bad.tar");dest.parent.mkdir(parents=True)
    with tarfile.open(dest,"w") as archive:
     item=tarfile.TarInfo("link");item.type=tarfile.SYMTYPE;item.linkname="target";archive.addfile(item)
    with self.assertRaises(ValueError):module.validate_quarantine_archive(dest)
 def test_filename_and_transfer_id_are_restricted(self):
  with tempfile.TemporaryDirectory() as tmp:
   module=self._module("linux",tmp)
   for transfer,filename in (("../x","mods.zip"),("transfer-1","../mods.zip"),("transfer-1","mods.exe")):
    with self.subTest(transfer=transfer,filename=filename),self.assertRaises(ValueError):module.quarantine_destination(transfer,filename)

if __name__=="__main__":unittest.main()
