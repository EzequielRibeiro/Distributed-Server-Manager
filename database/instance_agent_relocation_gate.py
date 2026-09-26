"""Centralized guard for mutating an instance during cross-Agent relocation."""
from __future__ import annotations

from alert_repository import AlertSession, dialect_for_backend

ACTIVE_SQL = "status NOT IN ('completed','failed')"


def active_relocation(backend, instance_id):
    if not instance_id:
        return None
    ph = dialect_for_backend(backend).placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                f"SELECT relocation_id,status FROM instance_agent_relocations "
                f"WHERE instance_id={ph} AND {ACTIVE_SQL} ORDER BY created_at DESC LIMIT 1",
                (str(instance_id),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            session.close()


def require_unlocked(backend, instance_id, *, requested_by=None):
    relocation = active_relocation(backend, instance_id)
    if relocation is None:
        return
    actor = str(requested_by or "")
    prefix = "relocation:" + relocation["relocation_id"]
    # All operational sub-phases belong to the same confirmed relocation.
    if actor == prefix or actor in {
        prefix + ":" + phase for phase in
        ("source-fence", "source-unfence", "source-start", "target-stop", "target-start")
    }:
        return
    raise RuntimeError(
        "instance migration in progress; changes are temporarily locked "
        f"({relocation['relocation_id']})"
    )


__all__ = ["ACTIVE_SQL", "active_relocation", "require_unlocked"]
