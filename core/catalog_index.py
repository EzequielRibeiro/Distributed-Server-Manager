"""Read-only Game -> Edition -> Distribution -> RuntimeDefinition index.

Only canonical published runtimes participate. Existing runtime IDs and payloads
are opaque execution contracts; this module never prepares or installs them.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "catalog" / "v2"


class CatalogIndex:
    def __init__(self, catalog_root=DEFAULT_ROOT):
        root = Path(catalog_root)
        self._games = {}
        self._runtimes = {}
        for path in sorted((root / "games").glob("*/game.json")):
            game = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(game, dict)
                    or set(game) != {"schema_version", "kind", "id", "name"}
                    or type(game.get("schema_version")) is not int
                    or game["schema_version"] != 2
                    or game.get("kind") != "GameDefinition"
                    or not isinstance(game.get("id"), str)
                    or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", game["id"])
                    or not isinstance(game.get("name"), str)
                    or not game["name"].strip()):
                raise ValueError(f"Invalid GameDefinition: {path}")
            if game["id"] != path.parent.name or game["id"] in self._games:
                raise ValueError(f"Duplicate or misplaced GameDefinition: {path}")
            self._games[game["id"]] = game
        for path in sorted((root / "games").glob("*/runtimes/*.json")):
            runtime = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(runtime, dict)
                    or runtime.get("kind") != "RuntimeDefinition"
                    or runtime.get("schema_version") != 2
                    or any(not isinstance(runtime.get(key), str) or not runtime[key].strip()
                           for key in ("id", "game", "edition", "variant"))):
                raise ValueError(f"Invalid RuntimeDefinition identity: {path}")
            if runtime["game"] not in self._games or runtime["game"] != path.parent.parent.name:
                raise ValueError(f"Runtime requires a matching GameDefinition: {path}")
            if runtime["id"] in self._runtimes:
                raise ValueError(f"Duplicate runtime ID: {runtime['id']}")
            self._runtimes[runtime["id"]] = runtime

    def runtime(self, runtime_id):
        """Return an independent copy of the original execution contract."""
        return deepcopy(self._runtimes[runtime_id])

    def hierarchy(self, game_id=None):
        """Return deterministic hierarchy; distributions use existing variant IDs.

        Multiple runtimes may share an edition/variant. Deferred definitions and
        games without published runtimes are excluded from discovery.
        """
        if game_id is not None and game_id not in self._games:
            raise KeyError(game_id)
        games = []
        for gid, definition in sorted(self._games.items()):
            if game_id is not None and gid != game_id:
                continue
            editions = {}
            for rid, runtime in sorted(self._runtimes.items()):
                if runtime["game"] == gid:
                    editions.setdefault(runtime["edition"], {}).setdefault(runtime["variant"], []).append(rid)
            if editions:
                games.append({**definition, "editions": [
                    {"id": eid, "distributions": [
                        {"id": variant, "runtime_definitions": ids}
                        for variant, ids in sorted(variants.items())]}
                    for eid, variants in sorted(editions.items())]})
        return deepcopy({"schema_version": 2, "kind": "CatalogIndex", "games": games})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--game")
    args = parser.parse_args()
    try:
        print(json.dumps(CatalogIndex(args.root).hierarchy(args.game), indent=2))
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, f"Catalog index error: {exc}\n")


if __name__ == "__main__":
    main()
