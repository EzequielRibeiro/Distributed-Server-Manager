#!/usr/bin/env python3
"""No third-party redistribution of author-restricted CurseForge members."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"core"))
from minecraft_modpack_resolver import _cf_download
from minecraft_content_resolver import MinecraftContentResolverError

class CurseForgeDistributionTest(unittest.TestCase):
 def test_explicit_author_restriction_blocks_without_requesting_download_url(self):
  calls=[]
  def requester(url,headers):
   calls.append(url)
   raise AssertionError("Third-party download is not permitted")
  with self.assertRaises(MinecraftContentResolverError) as caught:
   _cf_download(1111501,{"id":7936868,"downloadUrl":None},
      "dummy-key",requester,{"name":"I'm Fast","allowModDistribution":False})
  message=str(caught.exception)
  self.assertIn("I'm Fast",message)
  self.assertIn("1111501",message)
  self.assertIn("7936868",message)
  self.assertIn("autor",message)
  self.assertNotIn("dummy-key",message)
  self.assertEqual([],calls)

 def test_403_on_download_endpoint_reports_file_identity_not_bad_global_key(self):
  def requester(url,headers):
   assert url.endswith("/mods/1111501/files/7936868/download-url")
   assert headers=={"x-api-key":"dummy-key"}
   exc=HTTPError(url,403,"Forbidden",None,None)
   raise MinecraftContentResolverError("CurseForge não autorizado: verifique a API key no Controller.") from exc
  with self.assertRaises(MinecraftContentResolverError) as caught:
   _cf_download(1111501,{"id":7936868,"downloadUrl":""},
       "dummy-key",requester,{"name":"I'm Fast"})
  message=str(caught.exception)
  self.assertIn("CurseForge recusou o download",message)
  self.assertIn("I'm Fast",message)
  self.assertIn("7936868",message)
  self.assertNotIn("verifique a API key",message)
  self.assertNotIn("dummy-key",message)

 def test_regular_download_url_keeps_https_guard_and_no_extra_request(self):
  def requester(url,headers):raise AssertionError("Unexpected URL lookup")
  project={"name":"Other Mod","allowModDistribution":True}
  self.assertEqual("https://edge.forgecdn.net/mod.jar",
     _cf_download(3,{"id":8,"downloadUrl":"https://edge.forgecdn.net/mod.jar"},
                  "dummy-key",requester,project))
  with self.assertRaises(MinecraftContentResolverError):
   _cf_download(3,{"id":8,"downloadUrl":"http://bad.example/mod.jar"},
                "dummy-key",requester,project)

 def test_other_http_errors_remain_explicit_not_labeled_as_author_restrictions(self):
  def requester(url,headers):
   raise MinecraftContentResolverError("CurseForge limit exceeded") from HTTPError(url,429,"limit",None,None)
  with self.assertRaisesRegex(MinecraftContentResolverError,"limit exceeded"):
   _cf_download(3,{"id":8},"dummy-key",requester,{"name":"Other Mod"})

if __name__=="__main__":
 unittest.main()
