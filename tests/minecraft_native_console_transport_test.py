from __future__ import annotations

import importlib.util
from pathlib import Path
import socket
import tempfile
import threading


ROOT = Path(__file__).resolve().parents[1]

RUNTIME = ROOT / "agents/linux/runtime"
COMMON = ROOT / "agents/common"
PRIVILEGED = ROOT / "agents/linux/privileged"

import sys

for value in (
    RUNTIME,
    COMMON,
    PRIVILEGED,
):
    item = str(value)
    if item not in sys.path:
        sys.path.insert(0, item)

MODULE = (
    ROOT
    / "agents/linux/privileged/native_command.py"
)

SPEC = importlib.util.spec_from_file_location(
    "native_command_test_module",
    MODULE,
)

assert SPEC is not None
assert SPEC.loader is not None

NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


def record():
    return {
        "instance_id": "minecraft-001",
        "agent_id": "agent-one",
        "game_id": "minecraft",
        "environment_id": "minecraft.java.youer",
    }


def test_native_console_sends_exact_command(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "console.sock"
        listener = socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        )
        listener.bind(str(path))
        listener.listen(1)

        observed = []

        def server():
            conn, _ = listener.accept()
            with conn:
                data = bytearray()

                while True:
                    chunk = conn.recv(1024)

                    if not chunk:
                        break

                    data.extend(chunk)

                observed.append(
                    bytes(data)
                )

                conn.sendall(b"OK\n")

            listener.close()

        thread = threading.Thread(
            target=server,
        )
        thread.start()

        monkeypatch.setattr(
            NATIVE,
            "_minecraft_console_socket",
            lambda _record: path,
        )

        assert (
            NATIVE._minecraft_stdin(
                record(),
                "lp info",
            )
            is True
        )

        thread.join(timeout=2)

        assert observed == [
            b"lp info\n"
        ]


def test_native_console_absent_requests_rcon_fallback(
    monkeypatch,
):
    path = Path(
        "/definitely/not/a/capivara/socket"
    )

    monkeypatch.setattr(
        NATIVE,
        "_minecraft_console_socket",
        lambda _record: path,
    )

    assert (
        NATIVE._minecraft_stdin(
            record(),
            "list",
        )
        is False
    )


def test_native_console_rejects_failed_ack(
    monkeypatch,
):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "console.sock"

        listener = socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        )
        listener.bind(str(path))
        listener.listen(1)

        def server():
            conn, _ = listener.accept()

            with conn:
                while conn.recv(1024):
                    pass

                conn.sendall(
                    b"ERROR stdin unavailable\n"
                )

            listener.close()

        thread = threading.Thread(
            target=server,
        )
        thread.start()

        monkeypatch.setattr(
            NATIVE,
            "_minecraft_console_socket",
            lambda _record: path,
        )

        try:
            NATIVE._minecraft_stdin(
                record(),
                "lp info",
            )
        except RuntimeError as exc:
            assert (
                "stdin unavailable"
                in str(exc)
            )
        else:
            raise AssertionError(
                "transport failure was accepted"
            )

        thread.join(timeout=2)


def _write_native_request(root: Path, command_id: str) -> None:
    import json

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        root
        / f"{command_id}.request.json"
    ).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": (
                    "CapivaraPrivilegedNativeCommandRequest"
                ),
                "command_id": command_id,
                "instance_id": "minecraft-001",
                "agent_id": "agent-one",
                "operation": "console",
                "command": "lp info",
            }
        ),
        encoding="utf-8",
    )


def test_run_prefers_native_stdin_when_available(
    monkeypatch,
):
    import json

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        requests = root / "requests"
        config = root / "agent.json"
        command_id = "native-test-stdin"

        _write_native_request(
            requests,
            command_id,
        )

        config.write_text(
            json.dumps(
                {
                    "agent_id": "agent-one",
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            NATIVE.os,
            "geteuid",
            lambda: 0,
        )
        monkeypatch.setattr(
            NATIVE,
            "REQUEST_ROOT",
            requests,
        )
        monkeypatch.setattr(
            NATIVE,
            "CONFIG_PATH",
            config,
        )
        monkeypatch.setattr(
            NATIVE.instance_runtime,
            "get_instance",
            lambda _iid: record(),
        )
        monkeypatch.setattr(
            NATIVE,
            "_minecraft_stdin",
            lambda _record, _command: True,
        )

        def reject_rcon(*_args, **_kwargs):
            raise AssertionError(
                "RCON must not be used when "
                "native stdin is available"
            )

        monkeypatch.setattr(
            NATIVE,
            "_minecraft_rcon",
            reject_rcon,
        )

        result = NATIVE.run(
            command_id
        )

        assert result["status"] == "completed"
        assert result["transport"] == "minecraft-stdin"
        assert result["output"] == []

        persisted = json.loads(
            (
                requests
                / f"{command_id}.result.json"
            ).read_text(
                encoding="utf-8",
            )
        )

        assert (
            persisted["transport"]
            == "minecraft-stdin"
        )


def test_run_falls_back_to_rcon_without_native_socket(
    monkeypatch,
):
    import json

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        requests = root / "requests"
        config = root / "agent.json"
        command_id = "native-test-rcon"

        _write_native_request(
            requests,
            command_id,
        )

        config.write_text(
            json.dumps(
                {
                    "agent_id": "agent-one",
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            NATIVE.os,
            "geteuid",
            lambda: 0,
        )
        monkeypatch.setattr(
            NATIVE,
            "REQUEST_ROOT",
            requests,
        )
        monkeypatch.setattr(
            NATIVE,
            "CONFIG_PATH",
            config,
        )
        monkeypatch.setattr(
            NATIVE.instance_runtime,
            "get_instance",
            lambda _iid: record(),
        )
        monkeypatch.setattr(
            NATIVE,
            "_minecraft_stdin",
            lambda _record, _command: False,
        )
        monkeypatch.setattr(
            NATIVE,
            "_minecraft_rcon",
            lambda _record, _command: [
                "RCON OK"
            ],
        )

        result = NATIVE.run(
            command_id
        )

        assert result["status"] == "completed"
        assert result["transport"] == "minecraft-rcon"
        assert result["output"] == [
            "RCON OK"
        ]

        persisted = json.loads(
            (
                requests
                / f"{command_id}.result.json"
            ).read_text(
                encoding="utf-8",
            )
        )

        assert (
            persisted["transport"]
            == "minecraft-rcon"
        )
