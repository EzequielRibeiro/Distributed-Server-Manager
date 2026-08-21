#!/usr/bin/env python3
"""Create or validate the initial Region/Datacenter topology."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DATABASE_DIR = Path(__file__).resolve().parent
if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(0, str(DATABASE_DIR))

import manager
from backend_factory import create_backend
from alert_repository import AlertSession, dialect_for_backend


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bootstrap initial Capivara topology")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--region-id", required=True)
    p.add_argument("--region-name", required=True)
    p.add_argument("--region-country-code", default="")
    p.add_argument("--datacenter-id", required=True)
    p.add_argument("--datacenter-name", required=True)
    p.add_argument("--datacenter-provider", default="")
    p.add_argument("--datacenter-city", default="")
    p.add_argument("--datacenter-country-code", default="")
    return p


def _database_config(root: Path):
    args = manager.build_parser().parse_args(["--root", str(root), "status"])
    return manager.config_from_args(args)


def _row_value(row, key: str):
    try:
        return row[key]
    except (KeyError, TypeError):
        return getattr(row, key, None)


def bootstrap(backend, args: argparse.Namespace) -> None:
    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder

    with backend.transaction() as connection:
        session = AlertSession(backend, connection)
        try:
            region = session.execute(
                f"SELECT id,name,country_code FROM regions WHERE id={ph}",
                (args.region_id,),
            ).fetchone()

            if region is None:
                session.execute(
                    "INSERT INTO regions (id,name,country_code,status) "
                    f"VALUES ({ph},{ph},{ph},{ph})",
                    (
                        args.region_id,
                        args.region_name,
                        args.region_country_code or None,
                        "active",
                    ),
                )
            else:
                existing_name = str(_row_value(region, "name") or "")
                if existing_name and existing_name != args.region_name:
                    raise RuntimeError(
                        f"Region {args.region_id} already exists with name {existing_name!r}"
                    )

            datacenter = session.execute(
                f"SELECT id,region_id,name FROM datacenters WHERE id={ph}",
                (args.datacenter_id,),
            ).fetchone()

            if datacenter is None:
                session.execute(
                    "INSERT INTO datacenters "
                    "(id,region_id,name,provider,city,country_code,status) "
                    f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                    (
                        args.datacenter_id,
                        args.region_id,
                        args.datacenter_name,
                        args.datacenter_provider or None,
                        args.datacenter_city or None,
                        args.datacenter_country_code or None,
                        "active",
                    ),
                )
            else:
                existing_region = str(_row_value(datacenter, "region_id") or "")
                existing_name = str(_row_value(datacenter, "name") or "")
                if existing_region != args.region_id:
                    raise RuntimeError(
                        f"Datacenter {args.datacenter_id} already belongs to Region {existing_region}"
                    )
                if existing_name and existing_name != args.datacenter_name:
                    raise RuntimeError(
                        f"Datacenter {args.datacenter_id} already exists with name {existing_name!r}"
                    )
        finally:
            session.close()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    backend = create_backend(_database_config(args.root))
    try:
        bootstrap(backend, args)
    finally:
        backend.close()

    print(f"Initial topology ready: {args.region_id}/{args.datacenter_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
