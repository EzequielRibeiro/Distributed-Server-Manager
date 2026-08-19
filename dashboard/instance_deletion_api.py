"""HTTP-facing adapter for asynchronous instance deletion operations."""

from pathlib import Path

from instance_deletion_service import get_deletion_operation, start_deletion


def deletion_status(root: Path, instance_id: str) -> dict:
    operation = get_deletion_operation(root, instance_id)
    if not operation:
        return {"active": False, "state": "none"}
    operation = dict(operation)
    operation["active"] = operation.get("state") in {"queued", "stopping", "final_backup", "deleting"}
    return operation


def begin_deletion(root: Path, instance: Path, *, server: str, game: str, final_backup: bool, stop_instance, delete_record, audit):
    operation, accepted = start_deletion(
        root,
        instance,
        server=server,
        game=game,
        final_backup=final_backup,
        stop_instance=stop_instance,
        delete_record=delete_record,
        audit=audit,
    )
    return (202 if accepted else 409), operation
