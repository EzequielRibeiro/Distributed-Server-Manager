import threading
import time
from pathlib import Path
import pytest
from dashboard.instance_reinstall_service import reinstall_instance


def make_instance(tmp_path: Path, name="demo") -> Path:
    instance=tmp_path/name
    (instance/"serverfiles"/"mpmissions"/"mission"/"storage_1").mkdir(parents=True)
    (instance/"serverfiles"/"mpmissions"/"mission"/"storage_1"/"players.db").write_bytes(b"players")
    return instance


def test_reinstall_preserves_map_when_requested(tmp_path):
    instance=make_instance(tmp_path)
    def runner(preserve_config):
        import shutil
        shutil.rmtree(instance/"serverfiles"/"mpmissions")
        (instance/"serverfiles"/"mpmissions").mkdir()
        return {"ok":True,"runner_preserve_config":preserve_config}
    result=reinstall_instance(instance,preserve_config=True,preserve_map=True,runner=runner)
    assert (instance/"serverfiles"/"mpmissions"/"mission"/"storage_1"/"players.db").read_bytes()==b"players"
    assert result["preserve_config"] is True and result["preserve_map"] is True


def test_reinstall_can_replace_map(tmp_path):
    instance=make_instance(tmp_path)
    def runner(_):
        import shutil
        shutil.rmtree(instance/"serverfiles"/"mpmissions")
        (instance/"serverfiles"/"mpmissions").mkdir()
        return {"ok":True}
    reinstall_instance(instance,preserve_config=False,preserve_map=False,runner=runner)
    assert not (instance/"serverfiles"/"mpmissions"/"mission").exists()


def test_second_reinstall_is_blocked(tmp_path):
    instance=make_instance(tmp_path);entered=threading.Event();release=threading.Event()
    def runner(_):entered.set();release.wait(2);return {"ok":True}
    thread=threading.Thread(target=lambda:reinstall_instance(instance,preserve_config=True,preserve_map=True,runner=runner));thread.start();assert entered.wait(1)
    with pytest.raises(RuntimeError,match="reinstalação em andamento"):
        reinstall_instance(instance,preserve_config=True,preserve_map=True,runner=lambda _: {"ok":True})
    release.set();thread.join(2);assert not thread.is_alive()
