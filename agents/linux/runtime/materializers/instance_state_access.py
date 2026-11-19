"""Conservative, no-restart traversal repair for systemd-managed instance roots.

Only the root directory is touched. Never walk, chown, or chmod game content.
"""
from __future__ import annotations

import os
import pwd
import grp
import stat
from pathlib import Path

from .base import MaterializerError

_ROOT = Path("/var/lib/capivara-instances")
_OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def reconcile_instance_root_traversal(
    spec: dict, *, apply: bool = False,
    _parent: Path = _ROOT, _agent_user: str | None = None,
) -> str:
    """Audit or grant group traversal only when identities and paths are verified.

    _parent and _agent_user are internal test seams, never taken from runtime
    specs or remote commands. The default target is always the DSM-managed root.
    """
    instance_id = str(spec.get("instance_id") or "")
    if not instance_id or instance_id in (".", "..") or len(instance_id) > 191 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in instance_id):
        raise MaterializerError("invalid instance id for state access reconciliation")
    expected_path = str(_ROOT / instance_id)
    if str(spec.get("instance_state_root") or expected_path) != expected_path:
        return "custom_root_not_modified"

    parent_fd = None
    root_fd = None
    try:
        try:
            parent_fd = os.open(_parent, _OPEN_DIR)
        except FileNotFoundError:
            return "not_created"
        try:
            root_fd = os.open(instance_id, _OPEN_DIR, dir_fd=parent_fd)
        except FileNotFoundError:
            return "not_created"

        current = os.fstat(root_fd)
        try:
            service_user = pwd.getpwnam(str(spec["user"]))
            if _agent_user is None:
                # The Agent is a user on external nodes, but may be a
                # supplementary-group member on hybrid nodes.
                agent_groups = {grp.getgrnam("capivara-agent").gr_gid}
            else:
                agent_user = pwd.getpwnam(_agent_user)
                agent_groups = set(os.getgrouplist(_agent_user, agent_user.pw_gid))
        except (KeyError, OSError, ValueError) as exc:
            raise MaterializerError("unknown service owner or authorized Agent group") from exc
        if current.st_uid != service_user.pw_uid:
            raise MaterializerError("instance root owner differs from service user")
        if current.st_gid not in agent_groups:
            raise MaterializerError("instance root group is not accessible to Agent; refusing permission repair")
        mode = stat.S_IMODE(current.st_mode)
        if mode not in (0o700, 0o710):
            raise MaterializerError("unexpected instance root mode; refusing permission repair")
        if mode == 0o710:
            return "already_accessible"
        if not apply:
            return "needs_group_traverse"
        os.fchmod(root_fd, 0o710)
        if stat.S_IMODE(os.fstat(root_fd).st_mode) != 0o710:
            raise MaterializerError("instance root traversal repair did not persist")
        return "repaired"
    except MaterializerError:
        raise
    except OSError as exc:
        raise MaterializerError("unable to safely inspect or repair instance state root") from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)
        if parent_fd is not None:
            os.close(parent_fd)
