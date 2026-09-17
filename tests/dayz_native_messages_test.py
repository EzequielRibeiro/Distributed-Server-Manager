#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from agents.common.dayz_messages import (
    DayZMessagesError,
    DayZShutdownMessage,
    MANAGED_TEXT,
    deadline_minutes_for_due,
    materialize_shutdown_messages_xml,
    native_restart_plan,
    render_shutdown_messages_xml,
    resolve_dayz_mission,
)


class DayZNativeMessagesTest(unittest.TestCase):
    def _record(self, root: Path, *, arguments=None) -> dict:
        return {
            "instance_id": "dayz-001",
            "agent_id": "agent-001",
            "game_id": "dayz",
            "working_directory": str(root),
            "arguments": list(arguments or ["-config=serverDZ.cfg"]),
        }

    def test_renders_native_shutdown_countdown(self) -> None:
        payload = render_shutdown_messages_xml(DayZShutdownMessage(360))
        root = ET.fromstring(payload)
        message = root.find('message')
        self.assertIsNotNone(message)
        self.assertEqual(message.findtext('delay'), '0')
        self.assertEqual(message.findtext('repeat'), '0')
        self.assertEqual(message.findtext('deadline'), '360')
        self.assertEqual(message.findtext('onConnect'), '0')
        self.assertEqual(message.findtext('shutdown'), '1')
        self.assertIn('#tmin', message.findtext('text') or '')

    def test_due_at_is_converted_to_startup_countdown_without_early_shutdown(self) -> None:
        now = datetime(2026, 9, 16, 20, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(deadline_minutes_for_due(now + timedelta(minutes=90), now=now), 90)
        self.assertEqual(deadline_minutes_for_due(now + timedelta(seconds=61), now=now), 2)
        self.assertEqual(deadline_minutes_for_due(now + timedelta(seconds=1), now=now), 1)

    def test_due_at_rejects_expired_naive_and_excessive_windows(self) -> None:
        now = datetime(2026, 9, 16, 20, 0, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(DayZMessagesError, 'future'):
            deadline_minutes_for_due(now, now=now)
        with self.assertRaisesRegex(DayZMessagesError, 'timezone-aware'):
            deadline_minutes_for_due(datetime(2026, 9, 17, 20, 0, 0), now=now)
        with self.assertRaisesRegex(DayZMessagesError, '7 day'):
            deadline_minutes_for_due(now + timedelta(days=8), now=now)

    def test_escapes_text_as_xml_and_enforces_dayz_limit(self) -> None:
        payload = render_shutdown_messages_xml(DayZShutdownMessage(15, 'Restart & update <soon> #tmin'))
        self.assertIn('Restart &amp; update &lt;soon&gt; #tmin', payload)
        self.assertEqual(ET.fromstring(payload).findtext('message/text'), 'Restart & update <soon> #tmin')
        with self.assertRaises(DayZMessagesError):
            render_shutdown_messages_xml(DayZShutdownMessage(15, 'x' * 161))

    def test_preserves_community_messages_and_replaces_only_capivara_entry(self) -> None:
        existing = f'''<?xml version="1.0" encoding="UTF-8"?>
<messages>
  <message><delay>5</delay><repeat>30</repeat><deadline>0</deadline><onConnect>1</onConnect><shutdown>0</shutdown><text>Community notice</text></message>
  <message><delay>0</delay><repeat>0</repeat><deadline>5</deadline><onConnect>0</onConnect><shutdown>1</shutdown><text>{MANAGED_TEXT}</text></message>
</messages>
'''
        payload = render_shutdown_messages_xml(DayZShutdownMessage(120), existing_xml=existing)
        root = ET.fromstring(payload)
        texts = [str(node.findtext('text') or '') for node in root.findall('message')]
        self.assertEqual(texts.count('Community notice'), 1)
        self.assertEqual(texts.count(MANAGED_TEXT), 1)
        managed = next(node for node in root.findall('message') if node.findtext('text') == MANAGED_TEXT)
        self.assertEqual(managed.findtext('deadline'), '120')

    def test_rejects_invalid_deadline_target_and_existing_xml(self) -> None:
        with self.assertRaises(DayZMessagesError):
            render_shutdown_messages_xml(DayZShutdownMessage(0))
        with self.assertRaises(DayZMessagesError):
            render_shutdown_messages_xml(DayZShutdownMessage(10081))
        with self.assertRaises(DayZMessagesError):
            render_shutdown_messages_xml(DayZShutdownMessage(5), existing_xml='<messages><message>')
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(DayZMessagesError):
                materialize_shutdown_messages_xml(Path(temporary) / 'serverDZ.cfg', DayZShutdownMessage(5))

    def test_resolves_mission_from_agent_owned_server_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'serverDZ.cfg').write_text(
                'hostname="Test";\nclass Missions { class DayZ { template="dayzOffline.chernarusplus"; }; };\n',
                encoding='utf-8',
            )
            mission, mission_root = resolve_dayz_mission(self._record(root))
            self.assertEqual(mission, 'dayzOffline.chernarusplus')
            self.assertEqual(mission_root, (root / 'mpmissions' / mission).resolve())

    def test_mission_launch_argument_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mission_path = root / 'mpmissions' / 'dayzOffline.enoch'
            mission, resolved = resolve_dayz_mission(
                self._record(root, arguments=[f'-mission={mission_path}', '-config=serverDZ.cfg'])
            )
            self.assertEqual(mission, 'dayzOffline.enoch')
            self.assertEqual(resolved, mission_path.resolve())

    def test_rejects_path_escape_and_non_dayz_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(DayZMessagesError, 'outside instance root'):
                resolve_dayz_mission(self._record(root, arguments=['-mission=../foreign/dayzOffline.enoch']))
            record = self._record(root)
            record['game_id'] = 'minecraft'
            with self.assertRaisesRegex(DayZMessagesError, 'game_id=dayz'):
                resolve_dayz_mission(record)

    def test_native_plan_derives_messages_path_without_controller_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mission = root / 'mpmissions' / 'dayzOffline.chernarusplus'
            mission.mkdir(parents=True)
            (root / 'serverDZ.cfg').write_text(
                'class Missions { class DayZ { template="dayzOffline.chernarusplus"; }; };\n',
                encoding='utf-8',
            )
            result = native_restart_plan(self._record(root), 90)
            self.assertEqual(result.messages_path, str((mission / 'db' / 'messages.xml').resolve()))
            self.assertEqual(result.message.deadline_minutes, 90)
            self.assertIn('<shutdown>1</shutdown>', result.xml)

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
