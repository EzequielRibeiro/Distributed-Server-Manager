
# Generic Network Port Allocation

Status: Active

## Principles

Capivara DSM is multi-game.

No game owns the allocator.

RuntimeDefinition declares the network endpoints required by a
specific runtime. The Controller selects a block from the ranges
configured for the selected Agent.

The database remains the authority for Capivara reservations:

    instance_ports

The allowed universe is stored separately:

    agent_port_ranges

## Allocation flow

    RuntimeDefinition.network
            |
            v
    Agent active ranges
            |
            v
    instance_ports reservations
            |
            v
    operating-system socket inspection
            |
            v
    generic block allocator
            |
            v
    atomic instance_ports reservation
            |
            v
    process/config application

## Atomicity

A runtime receives all of the ports in its profile or none.

The instance creation transaction owns both the instance record and
its network reservations.

PostgreSQL and MySQL serialize allocation per Agent using a row lock.
SQLite relies on its transaction locking semantics.

## Agent ranges

Agent ranges are Controller-owned persistent configuration.

The initial compatibility range is:

    TCP 24000-24999
    UDP 24000-24999

This is not a permanent per-game rule and may be changed through:

    dsm agent ports show
    dsm agent ports set
    dsm agent ports check

## Remote Agents

LocalPortInspector implements the existing local/hybrid path.

RemoteAgentPortInspector deliberately fails closed until the Agent
transport exposes trusted socket inspection.

The Controller must never assume that its own local sockets describe
a remote Agent.

## Runtime profiles

The initial profile set includes:

- DayZ
- Arma 3
- Rust
- Minecraft Bedrock

Luanti, Mindustry and additional Minecraft Java runtime profiles must
only be enabled after their protocol and application behavior are
validated against their process adapters.

## Dashboard RBAC

Admin:
- may read every Agent
- may edit every Agent range
- may force a range change that excludes an existing reservation

Controller:
- may read Agents belonging to its controller_id
- may edit ranges inside its controller_id
- may not force an unsafe range change

Customer:
- no Agent administration access

Operator:
- no Agent administration access in this phase

Backend authorization is authoritative; hiding controls in the
browser is not considered a security boundary.
