# Agent Storage Pool Administration

Storage Pools are administered as Controller-managed desired state in namespace `capivara.agent.storage`.

The Dashboard never edits `/etc/capivara-agent/agent.json` directly. It writes Universal Configuration desired state; the authenticated Agent validates and atomically applies it locally.

Administrative operations:

- create/update a pool;
- enable/disable a non-default pool;
- change the default pool;
- remove an unused non-default pool.

Safety rules:

- pool IDs and storage classes are bounded safe tokens;
- roots must be absolute and cannot be `/` or protected system paths;
- duplicate roots are rejected;
- the default pool cannot be disabled or removed;
- a pool reported as assigned by instance telemetry cannot be removed;
- at least one pool is always retained;
- changes emit semantic Controller events.

Events:

- `AGENT_STORAGE_POOL_CREATED`
- `AGENT_STORAGE_POOL_UPDATED`
- `AGENT_STORAGE_POOL_ENABLED`
- `AGENT_STORAGE_POOL_DISABLED`
- `AGENT_STORAGE_POOL_DEFAULT_CHANGED`
- `AGENT_STORAGE_POOL_REMOVED`

The Agent validates the complete resulting `storage_pools` configuration through the same `storage_pools.py` policy used by runtime placement/materialization before writing its local configuration.
