#!/usr/bin/env python3
"""Server Pack UI is explicitly gated behind a preview and customer confirmation."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ServerPackUIContractTest(unittest.TestCase):
 def test_authentication_and_separate_read_only_preview(self):
  src=(ROOT/"dashboard/customer_content_http.py").read_text()
  self.assertIn('UPLOAD_PREVIEW=UPLOAD+"/preview"',src)
  self.assertIn('if parsed.path==UPLOAD_PREVIEW:',src)
  self.assertIn('preview=api.preview_serverpack(user',src)
  self.assertIn('if parsed.path==UPLOAD_FINALIZE:',src)
  self.assertLess(src.index("if parsed.path==UPLOAD_PREVIEW"),src.index("if parsed.path==UPLOAD_FINALIZE"))

 def test_zip_requires_official_provider_metadata_and_consent(self):
  js=(ROOT/"dashboard/web/customer-instance-v2.js").read_text()
  for fragment in ('previewOfficialServerpack(', 'content-upload-cf-project',
                   'content-upload-cf-file', 'content-upload-loader-version',
                   'metadata.serverpack={format:"official-serverpack-v1"',
                   '/content/upload/preview', 'requires_stopped_instance',
                   'if(!confirm(intro+', 'await previewOfficialServerpack',
                   'type!=="modpack"||!/\\.zip$/i'):
   self.assertIn(fragment,js)
  self.assertEqual(js.count('metadata:await previewOfficialServerpack'),1)
  self.assertEqual(js.count('...await previewOfficialServerpack'),1)

 def test_workspace_never_auto_enables_a_serverpack(self):
  js=(ROOT/"dashboard/web/customer-instance-v2.js").read_text()
  self.assertTrue(js.index('if(!confirm(intro+')<js.index('return metadata\n}'))
  self.assertIn('scripts', (ROOT/"docs/MINECRAFT_OFFICIAL_SERVERPACK_IMPORT.md").read_text())
  html=(ROOT/"dashboard/web/customer-instance.html").read_text()
  self.assertIn('customer-instance-v2.js?v=25',html)


if __name__=="__main__":
 unittest.main()
