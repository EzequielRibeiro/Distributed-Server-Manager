#!/usr/bin/env python3
"""Only verified NeoForge serverpack children may contain a SPI language library."""
from __future__ import annotations
import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SERVICE="META-INF/services/net.neoforged.neoforgespi.language.IModLanguageLoader"
CLASS="com/kotori316/scala_lib/ScalaLanguageProvider.class"
PROVIDER="com.kotori316.scala_lib.ScalaLanguageProvider"
FLAGS={"provider":"local","ephemeral_upload":True,"serverpack_child_v1":True,
       "serverpack_loader":"neoforge","serverpack_loader_version":"26.1.2.109"}


def semantic(platform):
 root=ROOT/f"agents/{platform}/runtime"
 sys.path.insert(0,str(root))
 spec=importlib.util.spec_from_file_location(f"serverpack_language_semantic_{platform}",root/"content_semantic_validation.py")
 obj=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(obj)
 return obj


def library(root,*,include_service=True,include_class=True,manifest=True):
 root.mkdir(parents=True,exist_ok=True)
 jar=root/"scala-library-provider.jar"
 with zipfile.ZipFile(jar,"w") as z:
  if manifest:z.writestr("META-INF/MANIFEST.MF","Manifest-Version: 1.0\r\nFMLModType: LIBRARY\r\n")
  if include_service:z.writestr(SERVICE,PROVIDER+"\n")
  if include_class:z.writestr(CLASS,b"fixture class bytes")
 return jar


class NeoForgeLanguageLibraryTest(unittest.TestCase):
 def test_verified_official_language_library_is_accepted_but_not_arbitrary_upload(self):
  for platform in ("linux","windows"):
   api=semantic(platform)
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as td:
    root=Path(td)
    library(root)
    valid=api.validate_external_content_payload(root,{
     "provider":"local","game_id":"minecraft","content_type":"mod","artifact":dict(FLAGS)})
    self.assertEqual(valid["validator"],"minecraft-neoforge-language-library-v1")
    for changes in (
      {"serverpack_child_v1":False},
      {"serverpack_loader":"fabric"},
    ):
     artifact={**FLAGS,**changes}
     with self.subTest(artifact=artifact),self.assertRaises(api.ContentSemanticValidationError):
      api.validate_external_content_payload(root,{
       "provider":"local","game_id":"minecraft","content_type":"mod","artifact":artifact})
    non_upload={**FLAGS,"ephemeral_upload":False}
    self.assertEqual(api.validate_external_content_payload(root,{
       "provider":"local","game_id":"minecraft","content_type":"mod",
       "artifact":non_upload})["validator"],"not-required")

 def test_spoofed_manifest_or_service_without_class_fails_closed(self):
  for platform in ("linux","windows"):
   api=semantic(platform)
   for omitted in ("service","class","manifest"):
    with self.subTest(platform=platform,omitted=omitted),tempfile.TemporaryDirectory() as td:
     root=Path(td)
     library(root,include_service=omitted!="service",
             include_class=omitted!="class",manifest=omitted!="manifest")
     with self.assertRaisesRegex(api.ContentSemanticValidationError,"not a recognized Minecraft mod"):
      api.validate_external_content_payload(root,{
       "provider":"local","game_id":"minecraft","content_type":"mod","artifact":dict(FLAGS)})

 def test_ordinary_mod_marker_still_passes_original_validation(self):
  for platform in ("linux","windows"):
   api=semantic(platform)
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as td:
    root=Path(td);root.mkdir(exist_ok=True)
    with zipfile.ZipFile(root/"mod.jar","w") as z:
     z.writestr("META-INF/neoforge.mods.toml",'modLoader="javafml"')
    result=api.validate_external_content_payload(root,{
     "provider":"local","game_id":"minecraft","content_type":"mod",
     "artifact":{"provider":"local","ephemeral_upload":True}})
    self.assertEqual(result["validator"],"minecraft-mod-v1")


if __name__=="__main__":
 unittest.main()
