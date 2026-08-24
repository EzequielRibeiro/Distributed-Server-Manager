import json
from pathlib import Path

import pytest

from dashboard.customer_instance_creation import runtime_definition, runtime_directory


def write_runtime(root: Path, game: str, runtime_id: str) -> Path:
    target = runtime_directory(root, game)
    target.mkdir(parents=True)
    path = target / "stable.json"
    path.write_text(
        json.dumps({"id": runtime_id, "game": game, "network": {"ports": []}}),
        encoding="utf-8",
    )
    return path


def test_customer_runtime_lookup_uses_canonical_catalog_v2_layout(tmp_path):
    write_runtime(tmp_path, "dayz", "dayz.stable")

    definition = runtime_definition(tmp_path, "dayz", "dayz.stable")

    assert definition["id"] == "dayz.stable"
    assert runtime_directory(tmp_path, "dayz") == (
        tmp_path / "catalog" / "v2" / "games" / "dayz" / "runtimes"
    )


def test_customer_runtime_lookup_does_not_require_legacy_runtime_tree(tmp_path):
    write_runtime(tmp_path, "dayz", "dayz.stable")

    assert not (tmp_path / "catalog" / "v2" / "runtimes" / "dayz").exists()
    assert runtime_definition(tmp_path, "dayz", "dayz.stable")["id"] == "dayz.stable"


def test_customer_runtime_lookup_rejects_game_missing_from_catalog(tmp_path):
    with pytest.raises(ValueError, match="game is not available in the catalog"):
        runtime_definition(tmp_path, "missing-game", "missing.stable")


def test_customer_runtime_lookup_rejects_unknown_runtime(tmp_path):
    write_runtime(tmp_path, "dayz", "dayz.stable")

    with pytest.raises(ValueError, match="runtime definition not found"):
        runtime_definition(tmp_path, "dayz", "dayz.experimental")
