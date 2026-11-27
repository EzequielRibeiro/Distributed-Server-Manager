#!/usr/bin/env python3
"""Root-reviewed local PostgreSQL YARA-X lost-delivery maintenance.

Not a no-drain admission tool. Never redispatch or infer an operation's outcome.
Preview and apply both retain the Controller and Hybrid execution fences.
Run only from independently reviewed signed code in conventional maintenance.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import time

ROOT = Path("/opt/dsm")
STATE = Path("/var/lib/capivara-dsm-928")
RUN = Path("/run/capivara-dsm")
ID = re.compile(r"yarax-[0-9a-f]{32}\Z")
ACTIONS = {"install_engine", "install_rules", "test_scan", "rescan_content", "rollback_rules"}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def read_regular(path, *, uid=None, limit=1048576):
    require(path.resolve() == path, "unsafe evidence path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_size <= limit and not before.st_mode & 0o022
                and (uid is None or before.st_uid == uid), "unsafe evidence file")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        named = path.lstat()
        def identity(s):
            return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid,
                    s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(len(data) <= limit and identity(before) == identity(after)
                == identity(named), "evidence changed while reading")
        return data


def absent_transaction():
    for p in (STATE / "no-drain-pending.json",
              STATE / "no-drain-release-binding.json",
              STATE / "no-drain-agent-inventory.json",
              RUN / "no-drain-maintenance.json"):
        require(not os.path.lexists(p), "unfinished no-drain transaction: " + p.name)


def unit(name):
    output = subprocess.check_output(
        ["/usr/bin/systemctl", "show", name, "-p", "ActiveState",
         "-p", "MainPID", "-p", "User", "-p", "ExecMainStartTimestampMonotonic"],
        text=True, timeout=5)
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def daemon_identity():
    controller = unit("dsm-dashboard.service")
    worker = unit("dsm-dashboard-worker.service")
    for item in (controller, worker):
        require(item["ActiveState"] == "active" and int(item["MainPID"]) > 1
                and int(item["ExecMainStartTimestampMonotonic"]) > 0,
                "control plane not active")
    require(controller["User"] and controller["User"] == worker["User"],
            "control plane user mismatch")
    uid = pwd.getpwnam(controller["User"]).pw_uid
    require(uid > 0, "unsafe control plane user")
    for item in (controller, worker):
        pid = int(item["MainPID"])
        require((Path("/proc") / str(pid)).stat().st_uid == uid,
                "control plane process identity mismatch")
    env = (Path("/proc") / controller["MainPID"] / "environ").read_bytes().split(b"\0")
    keys = {}
    for raw in env:
        key, sep, value = raw.partition(b"=")
        if sep and key in (b"DSM_DATABASE_DRIVER", b"DSM_DATABASE_NAME",
                           b"DSM_DATABASE_HOST", b"DSM_DATABASE_PORT",
                           b"DSM928_CONTROLLER_AGENT_HTTP_FLOCK"):
            require(key not in keys, "duplicate Controller database configuration")
            keys[key] = value.decode("utf-8")
    require(keys.get(b"DSM_DATABASE_DRIVER") in ("postgresql", "postgres", "pgsql")
            and keys.get(b"DSM_DATABASE_HOST") in ("localhost", "127.0.0.1", "::1", "/var/run/postgresql")
            and keys.get(b"DSM_DATABASE_PORT", "5432") == "5432"
            and keys.get(b"DSM928_CONTROLLER_AGENT_HTTP_FLOCK") == "1",
            "requires local PostgreSQL and opted-in Controller fence")
    require(unit("capivara-agent.service").get("ActiveState") in ("inactive", "failed"),
            "standalone local Agent may still be executing")
    return controller, worker, uid, keys.get(b"DSM_DATABASE_NAME")


def retain_lock(stack, path, uid, deadline):
    for directory in path.parents:
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
                and not info.st_mode & 0o022, "unsafe lock parent")
    before = path.lstat()
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    stack.callback(os.close, fd)
    def checkpoint():
        named, held = path.lstat(), os.fstat(fd)
        require((named.st_dev, named.st_ino) == (held.st_dev, held.st_ino)
                == (before.st_dev, before.st_ino)
                and stat.S_ISREG(held.st_mode) and held.st_uid == uid
                and held.st_nlink == 1 and held.st_size == 0
                and stat.S_IMODE(held.st_mode) == 0o600, "unsafe lock witness")
    checkpoint()
    while True:
        require(time.monotonic() < deadline, "local maintenance lock deadline")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(0.05)
    checkpoint()
    return checkpoint


def sql(database, script, **variables):
    args = ["/usr/sbin/runuser", "-u", "postgres", "--", "/usr/bin/psql",
            "-X", "-qAt", "--no-password", "--host=/var/run/postgresql",
            "--port=5432", "--dbname=" + database, "-v", "ON_ERROR_STOP=1"]
    for key, value in variables.items():
        args.extend(("-v", key + "=" + value))
    output = subprocess.check_output(args + ["-f", "-"], input=script,
                                     text=True, timeout=15,
                                     env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    return json.loads(output)


# Queries contain no operator-provided identifiers. psql quotes variables as
# literals and the row compare includes original timestamps and action.
_SELECT = """
SELECT json_build_object(
  'hybrid', (SELECT count(*) FROM agents a JOIN nodes n ON n.id=a.node_id
             WHERE a.id=:'agent' AND a.status='active' AND n.role='hybrid'),
  'credentials', (SELECT count(*) FROM agent_credentials
                  WHERE agent_id=:'agent' AND status='active'),
  'rows', COALESCE((SELECT json_agg(row_to_json(q) ORDER BY q.operation_id)
     FROM (SELECT operation_id, agent_id, action, status, created_at,
                  delivered_at, updated_at, completed_at,
                  result_json IS NULL AS no_result,
                  last_error IS NULL AS no_error
           FROM yarax_admin_operations
           WHERE operation_id IN (SELECT jsonb_array_elements_text(:'ids'::jsonb))) q),
     '[]'::json));
"""


def eligible(report, agent, ids, now):
    require(report["hybrid"] == 1 and report["credentials"] == 0,
            "local Hybrid identity or independent credentials unverified")
    rows = report["rows"]
    require(len(rows) == len(ids) and {r["operation_id"] for r in rows} == set(ids),
            "operation inventory changed")
    for row in rows:
        require(row["agent_id"] == agent and row["action"] in ACTIONS
                and row["status"] == "delivered" and row["completed_at"] is None
                and row["no_result"] is True and row["no_error"] is True
                and row["delivered_at"] == row["updated_at"],
                "not an unconfirmed unchanged delivery")
        delivered = datetime.fromisoformat(row["delivered_at"].replace("Z", "+00:00"))
        require(delivered.tzinfo is not None and now - delivered >= timedelta(hours=24),
                "delivery not old enough for operator review")
    return rows


_UPDATE = """
BEGIN;
SET LOCAL statement_timeout='8s';
LOCK TABLE public.agents,public.nodes,public.agent_credentials IN SHARE MODE NOWAIT;
LOCK TABLE public.yarax_admin_operations IN SHARE ROW EXCLUSIVE MODE NOWAIT;
WITH expected AS (
    SELECT * FROM jsonb_to_recordset(:'rows'::jsonb)
        AS e(operation_id text,agent_id text,action text,created_at text,
             delivered_at text,updated_at text)
), matched AS (
    SELECT y.operation_id FROM public.yarax_admin_operations y JOIN expected e
      ON y.operation_id=e.operation_id AND y.agent_id=e.agent_id
      AND y.action=e.action AND y.created_at=e.created_at
      AND y.delivered_at=e.delivered_at AND y.updated_at=e.updated_at
    WHERE y.agent_id=:'agent' AND y.status='delivered'
      AND y.completed_at IS NULL AND y.result_json IS NULL AND y.last_error IS NULL
), changed AS (
    UPDATE public.yarax_admin_operations y SET
      status='failed', completed_at=:'stamp', updated_at=:'stamp',
      last_error='Delivery outcome unconfirmed; operator reconciliation; no replay.',
      result_json=json_build_object(
        'operation_id',y.operation_id,'action',y.action,'status','failed',
        'outcome','unconfirmed','reason','legacy_delivery_result_unavailable',
        'reviewed_by',:'actor','evidence',:'evidence','review_sha256',:'digest',
        'previous_status',y.status,'previous_updated_at',y.updated_at,
        'previous_delivered_at',y.delivered_at)::text
    WHERE y.operation_id IN (SELECT operation_id FROM matched)
      AND (SELECT count(*) FROM matched)=(SELECT count(*) FROM expected)
      AND (SELECT count(*) FROM public.agents a JOIN public.nodes n ON n.id=a.node_id
           WHERE a.id=:'agent' AND a.status='active' AND n.role='hybrid')=1
      AND NOT EXISTS (SELECT 1 FROM public.agent_credentials
                      WHERE agent_id=:'agent' AND status='active')
    RETURNING operation_id
)
SELECT json_build_object('updated',COALESCE(json_agg(operation_id ORDER BY operation_id),'[]'::json))
FROM changed;
COMMIT;
"""


def observation(database, agent, ids, uid):
    report = sql(database, "BEGIN READ ONLY; SET LOCAL statement_timeout='5s';" +
                 _SELECT + "COMMIT;", agent=agent, ids=json.dumps(ids))
    rows = eligible(report, agent, ids, datetime.now(timezone.utc))
    state = ROOT / "runtime/hybrid-agent-state/security/yara-x/admin-result.json"
    result_digest = None
    if os.path.lexists(state):
        raw = read_regular(state, uid=uid)
        value = json.loads(raw)
        require(type(value) is dict and value.get("status") in ("completed", "failed")
                and type(value.get("operation_id")) is str,
                "local result running or ambiguous")
        require(value["operation_id"] not in ids,
                "matching Agent result must be consumed, not reconciled")
        result_digest = hashlib.sha256(raw).hexdigest()
    return {"database": database, "agent_id": agent, "rows": rows,
            "other_result_sha256": result_digest,
            "outcome": "unconfirmed", "replay": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--operation", action="append", required=True)
    parser.add_argument("--confirm", help="exact SHA256 from preview")
    parser.add_argument("--evidence", help="operator-reviewed evidence reference (no secrets)")
    args = parser.parse_args()
    require(os.geteuid() == 0, "root conventional maintenance required")
    require(re.fullmatch(r"[A-Za-z0-9_]{1,63}", args.database), "invalid database")
    ids = sorted(args.operation)
    require(1 <= len(ids) <= 20 and len(ids) == len(set(ids))
            and all(ID.fullmatch(x) for x in ids), "invalid operation inventory")
    require(bool(args.confirm) == bool(args.evidence), "confirmation and evidence required together")
    if args.confirm:
        require(re.fullmatch(r"[0-9a-f]{64}", args.confirm)
                and 12 <= len(args.evidence.strip()) <= 1000, "invalid review evidence")
    absent_transaction()
    identity = daemon_identity()
    uid = identity[2]
    require(identity[3] == args.database, "database does not match active Controller")
    agent = read_regular(Path("/etc/capivara-dsm/agent-session-id"), uid=0, limit=192).decode().strip()
    require(re.fullmatch(r"[A-Za-z0-9._-]{1,191}", agent), "invalid pinned Hybrid identity")
    config = json.loads(read_regular(ROOT / "runtime/hybrid-agent-state/agent.json", uid=uid))
    require(config.get("agent_id") == agent, "Hybrid identity mismatch")

    with ExitStack() as stack:
        deadline = time.monotonic() + 45
        locks = [(STATE / "updater-admission.lock", 0),
                 (RUN / "controller-agent-http-admission.lock", uid),
                 (RUN / "controller-agent-http.lock", uid),
                 (RUN / "worker-operations/hybrid_agent_worker.lock", uid)]
        checkpoints = [retain_lock(stack, p, owner, deadline) for p, owner in locks]
        def checkpoint():
            absent_transaction()
            require(daemon_identity() == identity, "control plane identity changed")
            for verify in checkpoints:
                verify()
        checkpoint()
        report = observation(args.database, agent, ids, uid)
        digest = hashlib.sha256(json.dumps(report, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
        if not args.confirm:
            print(json.dumps({"review": report, "review_sha256": digest,
                              "database_changed": False}, indent=2))
            return 0
        require(args.confirm == digest, "review evidence changed; repeat preview")
        checkpoint()
        require(observation(args.database, agent, ids, uid) == report,
                "review evidence changed before apply")
        result = sql(args.database, _UPDATE, agent=agent, rows=json.dumps(report["rows"]),
                     actor="root:" + str(os.environ.get("SUDO_USER") or "root")[:128],
                     evidence=args.evidence.strip(), digest=digest,
                     stamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        require(result["updated"] == ids, "reconciliation not applied: row comparison failed")
        print(json.dumps({"updated": ids, "outcome": "unconfirmed",
                          "replayed": False, "database_changed": True}, indent=2))
        checkpoint()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit("YARA-X reconciliation blocked: " + str(exc))
