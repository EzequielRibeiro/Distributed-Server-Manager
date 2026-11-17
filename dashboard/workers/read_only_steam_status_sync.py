"""Explicit, operator-run Steam status sync; never schedules a game update."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def sync(instance_id: str, *, backend, probe):
    from server_update_repository import ServerUpdateRepository
    repo = ServerUpdateRepository(backend)
    row = repo._row(instance_id)
    if not row:
        raise KeyError(instance_id)
    selection = json.loads(row['selection_json'])
    if selection.get('provider') != 'steam':
        raise ValueError('Steam-only read-only sync')
    status = probe(selection)
    return repo.record_read_only_probe(instance_id, status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--apply', action='store_true', help='Persist detected builds; otherwise print only')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'database'))
    sys.path.insert(0, str(root / 'core'))
    from runtime_backend import backend_from_environment
    from hybrid_steam_version_probe import probe
    backend = backend_from_environment()
    if args.apply:
        print(json.dumps(sync(args.instance_id, backend=backend, probe=probe), sort_keys=True))
    else:
        from server_update_repository import ServerUpdateRepository
        row = ServerUpdateRepository(backend)._row(args.instance_id)
        if not row:
            raise KeyError(args.instance_id)
        selection = json.loads(row['selection_json'])
        print(json.dumps(probe(selection), sort_keys=True))

if __name__ == '__main__':
    main()
