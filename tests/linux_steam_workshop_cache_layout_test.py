#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from content_provider_steam_workshop import _cache_candidates


class LinuxSteamWorkshopCacheLayoutTest(unittest.TestCase):
    def test_detects_steam_local_share_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            executable = home / ".local" / "share" / "Steam" / "steamcmd" / "steamcmd.sh"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")

            previous_home = __import__("os").environ.get("HOME")
            __import__("os").environ["HOME"] = str(home)
            try:
                candidates = _cache_candidates(
                    str(executable),
                    root / "state" / "game-data",
                    "221100",
                    "1828439124",
                )
            finally:
                if previous_home is None:
                    __import__("os").environ.pop("HOME", None)
                else:
                    __import__("os").environ["HOME"] = previous_home

            expected = (
                home
                / ".local"
                / "share"
                / "Steam"
                / "steamapps"
                / "workshop"
                / "content"
                / "221100"
                / "1828439124"
            ).resolve()
            self.assertIn(expected, candidates)

    def test_detects_cache_next_to_steamcmd_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable = root / "Steam" / "steamcmd" / "steamcmd.sh"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")

            candidates = _cache_candidates(
                str(executable),
                root / "state" / "game-data",
                "221100",
                "1828439124",
            )

            expected = (
                executable.parent.parent
                / "steamapps"
                / "workshop"
                / "content"
                / "221100"
                / "1828439124"
            ).resolve()
            self.assertIn(expected, candidates)

    def test_detects_distro_steamcmd_home_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            executable = root / "usr" / "games" / "steamcmd"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")

            previous_home = __import__("os").environ.get("HOME")
            __import__("os").environ["HOME"] = str(home)
            try:
                candidates = _cache_candidates(
                    str(executable),
                    root / "state" / "game-data",
                    "221100",
                    "1828439124",
                )
            finally:
                if previous_home is None:
                    __import__("os").environ.pop("HOME", None)
                else:
                    __import__("os").environ["HOME"] = previous_home

            expected = (
                home
                / ".steam"
                / "steamcmd"
                / "steamapps"
                / "workshop"
                / "content"
                / "221100"
                / "1828439124"
            ).resolve()
            self.assertIn(expected, candidates)

    def test_detects_agent_state_managed_steamcmd_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            agent_state = root / "agent-state"
            executable = root / "usr" / "games" / "steamcmd"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")

            previous = __import__("os").environ.get("CAPIVARA_AGENT_STATE_DIR")
            __import__("os").environ["CAPIVARA_AGENT_STATE_DIR"] = str(agent_state)
            try:
                candidates = _cache_candidates(
                    str(executable),
                    root / "other-state" / "game-data",
                    "221100",
                    "1828439124",
                )
            finally:
                if previous is None:
                    __import__("os").environ.pop("CAPIVARA_AGENT_STATE_DIR", None)
                else:
                    __import__("os").environ["CAPIVARA_AGENT_STATE_DIR"] = previous

            expected = (
                agent_state
                / "tools"
                / "steamcmd"
                / "steamapps"
                / "workshop"
                / "content"
                / "221100"
                / "1828439124"
            ).resolve()
            self.assertIn(expected, candidates)


if __name__ == "__main__":
    unittest.main()
