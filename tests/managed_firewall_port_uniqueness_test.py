from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_instance_port_schema_enforces_node_protocol_port_uniqueness():
    expected = [
        "database/schemas/sqlite.sql",
        "database/schemas/postgresql.sql",
        "database/schemas/mysql.sql",
        "database/schemas/mariadb.sql",
    ]

    for relative in expected:
        source = (ROOT / relative).read_text(encoding="utf-8")

        normalized = " ".join(source.split())

        assert (
            "UNIQUE ( node_id, protocol, port )"
            in normalized
            or
            "UNIQUE (node_id, protocol, port)"
            in normalized
        ), relative


def test_allocator_enforces_numeric_port_ownership_across_protocols():
    source = (
        ROOT / "core" / "network" / "port_allocator.py"
    ).read_text(encoding="utf-8")

    assert "reserved_numbers" in source
    assert "occupied_numbers" in source
    assert "if port in reserved_numbers" in source
    assert "if port in occupied_numbers" in source


def test_linux_firewall_ownership_contains_protocol_and_port():
    source = (
        ROOT
        / "agents"
        / "linux"
        / "privileged"
        / "reconcile_firewall.py"
    ).read_text(encoding="utf-8")

    assert (
        'f"capivara:{_token(instance_id, \'instance_id\')}:'
        '{_token(name, \'port name\')}:{protocol}:{port}"'
        in source
    )
