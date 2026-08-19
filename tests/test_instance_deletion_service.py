import json
import time
from pathlib import Path

from dashboard.instance_deletion_service import get_deletion_operation, start_deletion


def wait_terminal(root: Path, instance_id: str, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = get_deletion_operation(root, instance_id)
        if state.get("state") in {"completed", "failed"}:
            return state
        time.sleep(0.02)
    raise AssertionError("deletion operation did not finish")


def test_repeated_delete_requests_share_one_operation_and_backup(tmp_path):
    instance = tmp_path / "instances" / "node-a" / "dayz" / "demo-001"
    instance.mkdir(parents=True)
    (instance / "serverfiles").mkdir()
    (instance / "serverfiles" / "server.bin").write_bytes(b"capivara" * 65536)

    deleted = []
    stopped = []
    audits = []

    def stop():
        stopped.append(True)

    def delete_record(instance_id):
        deleted.append(instance_id)
        return True

    def audit(action, result, detail):
        audits.append((action, result, detail))

    first, created = start_deletion(
        tmp_path,
        instance,
        server="node-a",
        game="dayz",
        final_backup=True,
        stop_instance=stop,
        delete_record=delete_record,
        audit=audit,
    )
    assert created is True

    operation_ids = {first["operation_id"]}
    for _ in range(9):
        current, _ = start_deletion(
            tmp_path,
            instance,
            server="node-a",
            game="dayz",
            final_backup=True,
            stop_instance=stop,
            delete_record=delete_record,
            audit=audit,
        )
        operation_ids.add(current["operation_id"])

    result = wait_terminal(tmp_path, "demo-001")
    assert result["state"] == "completed"
    assert len(operation_ids) == 1
    assert deleted == ["demo-001"]
    assert len(stopped) == 1
    backups = list((tmp_path / "backups" / "instances" / "demo-001").glob("final-delete-*.tar.gz"))
    assert len(backups) == 1
    assert not list((tmp_path / "backups" / "instances" / "demo-001").glob("*.part"))
    assert not instance.exists()


def test_failed_final_backup_preserves_instance(tmp_path, monkeypatch):
    import dashboard.instance_deletion_service as service

    instance = tmp_path / "instances" / "node-a" / "dayz" / "demo-002"
    instance.mkdir(parents=True)
    (instance / "data.bin").write_bytes(b"data")

    def fail_backup(*args, **kwargs):
        raise OSError("simulated backup failure")

    monkeypatch.setattr(service, "_final_backup", fail_backup)
    deleted = []

    start_deletion(
        tmp_path,
        instance,
        server="node-a",
        game="dayz",
        final_backup=True,
        stop_instance=lambda: None,
        delete_record=lambda instance_id: deleted.append(instance_id) or True,
        audit=lambda *args: None,
    )

    result = wait_terminal(tmp_path, "demo-002")
    assert result["state"] == "failed"
    assert "simulated backup failure" in result["error"]
    assert instance.is_dir()
    assert deleted == []
