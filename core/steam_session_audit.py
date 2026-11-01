#!/usr/bin/env python3
"""Metadata-only SteamCMD persistence audit. Never open credential files."""
from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from typing import Any

SESSION_FILES = (
    '.local/share/Steam/config/config.vdf',
    '.local/share/Steam/config/loginusers.vdf',
    '.local/share/Steam/steamcmd/config/config.vdf',
    '.steam/steam/config/config.vdf',
)


def _metadata(path: Path) -> dict[str, Any]:
    """Use lstat to avoid opening files, traversing final symlinks or exposing contents."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        return {'state': 'absent'}
    except OSError:
        return {'state': 'unavailable'}
    if stat.S_ISLNK(st.st_mode):
        return {'state': 'symlink', 'target_inspected': False}
    if not stat.S_ISREG(st.st_mode):
        return {'state': 'unexpected_type'}
    return {
        'state': 'present', 'size_bytes': st.st_size,
        'mtime_ns': st.st_mtime_ns,
        'inode': st.st_ino,
        'mode': format(stat.S_IMODE(st.st_mode), '04o'),
        'owner_matches_runtime': st.st_uid == os.geteuid(),
        'group_or_world_readable': bool(stat.S_IMODE(st.st_mode) & 0o044),
        'group_or_world_writable': bool(stat.S_IMODE(st.st_mode) & 0o022),
    }


def _path_within_home(path: Path, home: Path) -> bool:
    """Reject intermediate links that could redirect audit outside the chosen HOME."""
    current = home
    for part in path.relative_to(home).parts[:-1]:
        current = current / part
        try:
            if current.is_symlink():
                return False
        except OSError:
            return False
    return True


def snapshot(home: Path) -> dict[str, Any]:
    home = Path(home).expanduser().absolute()
    if not home.is_dir() or home.is_symlink():
        raise ValueError('Steam HOME must be a real existing directory')
    result: dict[str, Any] = {'schema_version': 1, 'kind': 'steam_session_metadata', 'files': {}}
    for relative in SESSION_FILES:
        path = home / relative
        result['files'][relative] = (
            _metadata(path) if _path_within_home(path, home)
            else {'state': 'intermediate_symlink', 'target_inspected': False}
        )
    return result


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old = before.get('files') or {}
    new = after.get('files') or {}
    return {'schema_version': 1, 'kind': 'steam_session_metadata_change',
            'changes': {key: 'changed' if old.get(key) != new.get(key) else 'unchanged'
                        for key in SESSION_FILES}}


def main() -> int:
    parser = argparse.ArgumentParser(description='Read Steam session file metadata without credential access')
    parser.add_argument('--home', type=Path, default=Path(os.environ.get('CAPIVARA_STEAM_HOME') or os.environ['HOME']))
    parser.add_argument('--compare-to', type=Path, help='previous audit JSON (contains metadata only)')
    args = parser.parse_args()
    current = snapshot(args.home)
    print(json.dumps(current, sort_keys=True))
    if args.compare_to:
        before = json.loads(args.compare_to.read_text(encoding='utf-8'))
        print(json.dumps(compare(before, current), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
