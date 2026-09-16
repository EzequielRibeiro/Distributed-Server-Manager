#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from agents.common.dayz_messages import (
    DayZMessagesError,
    DayZShutdownMessage,
    materialize_shutdown_messages_xml,
    render_shutdown_messages_xml,
)


class DayZNativeMessagesTest(unittest.TestCase):
    def test_renders_native_shutdown_countdown(self) -> None:
        payload = render_shutdown_messages_xml(DayZShutdownMessage(360))
        self.assertIn('<deadline>360</deadline>', payload)
        self.assertIn('<shutdown>1</shutdown>', payload)
        self.assertIn('#tmin', payload)
        root = ET.fromstring(payload)
        self.assertEqual(root.tag, 'messages')
        message = root.find('message')
        self.assertIsNotNone(message)
        self.assertEqual(message.findtext('deadline'), '360')
        self.assertEqual(message.findtext('shutdown'), '1')

    def test_escapes_text_as_xml(self) -> None:
        payload = render_shutdown_messages_xml(DayZShutdownMessage(15, 'Restart & update <soon> #tmin'))
        self.assertIn('Restart &amp; update &lt;soon&gt; #tmin', payload)
        self.assertEqual(ET.fromstring(payload).findtext('message/text'), 'Restart & update <soon> #tmin')

    def test_rejects_invalid_deadline_and_target(self) -> None:
        with self.assertRaises(DayZMessagesError):
            render_shutdown_messages_xml(DayZShutdownMessage(0))
        with self.assertRaises(DayZMessagesError):
            render_shutdown_messages_xml(DayZShutdownMessage(10081))
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(DayZMessagesError):
                materialize_shutdown_messages_xml(Path(temporary) / 'serverDZ.cfg', DayZShutdownMessage(5))

    def test_materializes_atomically_to_messages_xml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'mpmissions' / 'dayzOffline.chernarusplus' / 'db' / 'messages.xml'
            result = materialize_shutdown_messages_xml(target, DayZShutdownMessage(30))
            self.assertEqual(result, target)
            self.assertTrue(target.is_file())
            self.assertEqual(ET.parse(target).getroot().findtext('message/deadline'), '30')
            self.assertEqual(list(target.parent.glob('.messages.xml.*')), [])


if __name__ == '__main__':
    unittest.main()
