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



def harden_session_file(home: Path, relative: str) -> str:
    """Restrict an owned regular file to 0600; never read its bytes.

    Open each directory relative to an already-validated directory descriptor to
    avoid symlink substitution; the final descriptor is only used with fstat and
    fchmod. Never create, truncate, delete or rewrite Steam state.
    """
    if relative not in SESSION_FILES:
        raise ValueError('Unrecognized Steam session file')
    home = Path(home).expanduser().absolute()
    components = Path(relative).parts
    flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
    dir_flags = flags | os.O_DIRECTORY
    fd = os.open(home, dir_flags)
    try:
        for component in components[:-1]:
            child_fd = os.open(component, dir_flags, dir_fd=fd)
            os.close(fd)
            fd = child_fd
        try:
            file_fd = os.open(components[-1], flags | getattr(os, 'O_NONBLOCK', 0), dir_fd=fd)
        except FileNotFoundError:
            return 'absent'
        try:
            st = os.fstat(file_fd)
            if not stat.S_ISREG(st.st_mode):
                raise ValueError('Steam session path is not a regular file')
            if st.st_uid != os.geteuid():
                raise PermissionError('Refusing to change an unowned Steam session file')
            if stat.S_IMODE(st.st_mode) == 0o600:
                return 'already_secure'
            os.fchmod(file_fd, 0o600)
            return 'secured'
        finally:
            os.close(file_fd)
    finally:
        os.close(fd)

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
    parser.add_argument('--harden', action='store_true', help='opt-in: restrict owned session file permissions to 0600 without reading bytes')
    args = parser.parse_args()
    if args.harden:
        results = {}
        for relative in SESSION_FILES:
            try:
                results[relative] = harden_session_file(args.home, relative)
            except (OSError, ValueError) as exc:
                results[relative] = 'skipped_' + type(exc).__name__
        print(json.dumps({'kind': 'steam_session_permission_hardening', 'results': results}, sort_keys=True))
    current = snapshot(args.home)
    print(json.dumps(current, sort_keys=True))
    if args.compare_to:
        before = json.loads(args.compare_to.read_text(encoding='utf-8'))
        print(json.dumps(compare(before, current), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
