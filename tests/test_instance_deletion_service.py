import tarfile
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


def test_repeated_requests_are_rejected_while_delete_operates(tmp_path):
    instance = tmp_path / "instances" / "node-a" / "dayz" / "demo-001"
    instance.mkdir(parents=True)
    (instance / "serverDZ.cfg").write_text("hostname=Capivara")
    calls = []
    def stop():
        time.sleep(0.15)
        calls.append("stop")
    first, accepted = start_deletion(tmp_path, instance, server="node-a", game="dayz", final_backup=True, stop_instance=stop, delete_record=lambda _: True, audit=lambda *args: None)
    assert accepted is True
    for _ in range(9):
        current, accepted = start_deletion(tmp_path, instance, server="node-a", game="dayz", final_backup=True, stop_instance=stop, delete_record=lambda _: True, audit=lambda *args: None)
        assert accepted is False
        assert current["busy"] is True
        assert current["operation_id"] == first["operation_id"]
    assert wait_terminal(tmp_path, "demo-001")["state"] == "completed"
    assert calls == ["stop"]


def test_final_backup_is_selective_and_excludes_game_binary(tmp_path):
    instance = tmp_path / "instances" / "node-a" / "dayz" / "demo-002"
    (instance / "mpmissions" / "dayzOffline.chernarusplus" / "storage_1").mkdir(parents=True)
    (instance / "serverfiles").mkdir()
    (instance / "serverDZ.cfg").write_text("hostname=Capivara")
    (instance / "mpmissions" / "dayzOffline.chernarusplus" / "init.c").write_text("void main() {}")
    (instance / "mpmissions" / "dayzOffline.chernarusplus" / "storage_1" / "players.db").write_bytes(b"map-state")
    (instance / "serverfiles" / "DayZServer").write_bytes(b"large-game-binary")
    start_deletion(tmp_path, instance, server="node-a", game="dayz", final_backup=True, stop_instance=lambda: None, delete_record=lambda _: True, audit=lambda *args: None)
    assert wait_terminal(tmp_path, "demo-002")["state"] == "completed"
    backup = tmp_path / "backups" / "instances" / "demo-002" / "final-delete.tar.gz"
    with tarfile.open(backup, "r:gz") as archive:
        names = set(archive.getnames())
    assert "demo-002/serverDZ.cfg" in names
    assert "demo-002/mpmissions/dayzOffline.chernarusplus/init.c" in names
    assert "demo-002/mpmissions/dayzOffline.chernarusplus/storage_1/players.db" in names
    assert "demo-002/serverfiles/DayZServer" not in names


def test_new_final_backup_replaces_previous_archive(tmp_path):
    from dashboard.instance_deletion_service import _final_backup
    instance = tmp_path / "instances" / "node-a" / "dayz" / "demo-003"
    instance.mkdir(parents=True)
    config = instance / "serverDZ.cfg"
    config.write_text("version=old")
    _final_backup(tmp_path, instance, {"operation_id": "one", "instance_id": "demo-003"})
    backup = tmp_path / "backups" / "instances" / "demo-003" / "final-delete.tar.gz"
    first = backup.read_bytes()
    config.write_text("version=new-and-different")
    _final_backup(tmp_path, instance, {"operation_id": "two", "instance_id": "demo-003"})
    assert backup.read_bytes() != first
    assert len(list(backup.parent.glob("final-delete*.tar.gz"))) == 1
    assert not list(backup.parent.glob("*.part"))


def test_backup_failure_preserves_instance_and_previous_archive(tmp_path, monkeypatch):
    import dashboard.instance_deletion_service as service
    instance = tmp_path / "instances" / "node-a" / "dayz" / "demo-004"
    instance.mkdir(parents=True)
    (instance / "serverDZ.cfg").write_text("data")
    backup_dir = tmp_path / "backups" / "instances" / "demo-004"
    backup_dir.mkdir(parents=True)
    previous = backup_dir / "final-delete.tar.gz"
    previous.write_bytes(b"previous-valid-backup")
    monkeypatch.setattr(service, "_final_backup", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("simulated backup failure")))
    deleted = []
    start_deletion(tmp_path, instance, server="node-a", game="dayz", final_backup=True, stop_instance=lambda: None, delete_record=lambda instance_id: deleted.append(instance_id) or True, audit=lambda *args: None)
    result = wait_terminal(tmp_path, "demo-004")
    assert result["state"] == "failed"
    assert instance.is_dir()
    assert deleted == []
    assert previous.read_bytes() == b"previous-valid-backup"
