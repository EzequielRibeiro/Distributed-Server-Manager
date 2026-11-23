#!/usr/bin/env python3
"""#928: authenticated Controller to root-owned NEGATIVE v2 receipt writer.

The Dashboard uses a preprovisioned root-owned AF_UNIX systemd socket. The
server verifies SO_PEERCRED and the Dashboard cgroup/PID before allowing any
one-use negative journal append. The socket is NOT enabled by a release or
update automatically; absent or insecure infrastructure fails closed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
from typing import Any, Mapping

SOCKET_PATH = Path("/run/capivara-dsm/dsm928-wire-replay.sock")
PROTOCOL = "dsm928-root-negative-wire-writer-v1"
EXPECTED_KEYS = frozenset({
    "status", "transaction_id", "release_sha256", "request_id",
    "remote_agent_quiescence_acked", "external_jobs_acked",
    "live_no_drain_authorized",
})


class PrivilegedReplayUnavailable(RuntimeError):
    pass


def _connect_writer() -> socket.socket:
    # All directories must be root-owned, non-writable by non-root and
    # pre-existing. The socket inode itself is owned by the DSM user 0600.
    for directory in (Path("/run"), SOCKET_PATH.parent):
        try:
            info = directory.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                    or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
                raise PrivilegedReplayUnavailable("writer_socket_parent_untrusted")
        except OSError as exc:
            raise PrivilegedReplayUnavailable("writer_socket_parent_missing") from exc
    try:
        before = SOCKET_PATH.lstat()
        if (not stat.S_ISSOCK(before.st_mode)
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_uid != os.geteuid()):
            raise PrivilegedReplayUnavailable("privileged_socket_inode_untrusted")
        wire = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        wire.settimeout(4.0)
        try:
            wire.connect(str(SOCKET_PATH))
            after = SOCKET_PATH.lstat()
            if (not stat.S_ISSOCK(after.st_mode)
                    or (after.st_dev, after.st_ino) !=
                    (before.st_dev, before.st_ino)):
                raise PrivilegedReplayUnavailable("privileged_socket_replaced")
            # SO_PEERCRED on the client side verifies that the accepting
            # systemd unit is root-owned, not a user-supplied socket server.
            import struct
            values = wire.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _pid, uid, _gid = struct.unpack("3i", values)
            if uid != 0:
                raise PrivilegedReplayUnavailable("writer_peer_not_root")
            return wire
        except BaseException:
            wire.close()
            raise
    except OSError as exc:
        raise PrivilegedReplayUnavailable("root_wire_writer_unavailable") from exc


def commit_authenticated_negative_v2_receipt(
    *, authenticated_agent_id: str, receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Send an already credentialed receipt; do not claim an operational ACK."""
    if (type(authenticated_agent_id) is not str
            or not isinstance(receipt, Mapping)
            or receipt.get("status") != "authenticated_evidence_received_unfenced"
            or receipt.get("contract") != {
                "protocol": "dsm928-fence-evidence-release-bound-readonly-v2",
                "schema": "2",
            }):
        raise PrivilegedReplayUnavailable("only_authenticated_negative_v2_allowed")
    request = {
        "protocol": PROTOCOL,
        "authenticated_agent_id": authenticated_agent_id,
        "receipt": dict(receipt),
    }
    try:
        encoded = (json.dumps(request, sort_keys=True, separators=(",", ":"))
                   + "\n").encode("ascii")
        if len(encoded) > 8192:
            raise PrivilegedReplayUnavailable("wire_request_oversized")
        with _connect_writer() as wire:
            wire.sendall(encoded)
            response = bytearray()
            while b"\n" not in response and len(response) < 4096:
                packet = wire.recv(4096-len(response))
                if not packet:
                    break
                response.extend(packet)
        if (not response.endswith(b"\n") or b"\n" in response[:-1]
                or len(response) > 4096):
            raise PrivilegedReplayUnavailable("writer_response_malformed")
        answer = json.loads(response)
        if (not isinstance(answer, dict) or set(answer) != EXPECTED_KEYS
                or answer.get("status") != "negative_v2_receipt_durably_recorded"
                or answer.get("transaction_id") != receipt.get("transaction_id")
                or answer.get("release_sha256") != receipt.get("release_sha256")
                or answer.get("request_id") != receipt.get("request_id")
                or answer.get("remote_agent_quiescence_acked") is not False
                or answer.get("external_jobs_acked") is not False
                or answer.get("live_no_drain_authorized") is not False):
            raise PrivilegedReplayUnavailable("writer_response_untrusted_or_blocked")
        return answer
    except (OSError, ValueError, TypeError, UnicodeError,
            socket.timeout) as exc:
        raise PrivilegedReplayUnavailable("writer_io_or_protocol_failure") from exc


def inspect_positive_quiescence_claim(
    claim: Mapping[str, Any], *, transaction_id: str,
    release_sha256: str, expected_processes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Conservative schema inspection only; NEVER an operational ACK.

    An actual ACK requires independently authenticated, continuously fenced
    processes and durable cross-host recovery. A caller-provided claim cannot
    establish those facts. This function intentionally has no authorization
    output that can be interpreted as True.
    """
    import re
    reasons = []
    if not isinstance(claim, Mapping):
        reasons.append("claim_not_mapping")
        claim = {}
    if not isinstance(transaction_id, str) or not re.fullmatch(
            r"[0-9a-f]{32}", transaction_id):
        reasons.append("invalid_transaction")
    if not isinstance(release_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", release_sha256):
        reasons.append("invalid_release_pin")
    if claim.get("transaction_id") != transaction_id:
        reasons.append("transaction_mismatch")
    if claim.get("release_sha256") != release_sha256:
        reasons.append("release_mismatch")
    if not isinstance(expected_processes, Mapping) or not expected_processes:
        reasons.append("authoritative_process_inventory_missing")
    elif not all(isinstance(k, str) and k and isinstance(v, Mapping)
                 and v for k, v in expected_processes.items()):
        reasons.append("invalid_process_inventory")
    if claim.get("live_no_drain_authorized") is not False:
        reasons.append("authorization_claim_forbidden")
    # A positive assertion in untrusted JSON is not a kernel-backed fence.
    reasons.append("positive_process_fencing_not_independently_verified")
    reasons.append("cross_host_lease_and_recovery_not_verified")
    return {
        "status": "blocked",
        "blockers": sorted(set(reasons)),
        "controller_mutations_acked": False,
        "worker_cycles_acked": False,
        "remote_agents_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }
