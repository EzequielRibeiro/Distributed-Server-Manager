# P0-G — SYSTEM / CONTRACT / CUSTOMER precedence

Capivara DSM uses one authority order for configuration resolution:

`SYSTEM > CONTRACT > CUSTOMER`

The rule is independent of UI, game and runtime. Input layer order does not affect authority.

## Semantics

- **SYSTEM**: platform/operator decisions. A value defined here cannot be replaced by CONTRACT or CUSTOMER.
- **CONTRACT**: commercial/contractual decisions. A value defined here wins over CUSTOMER when SYSTEM does not define it.
- **CUSTOMER**: customer preference. It becomes effective only where neither SYSTEM nor CONTRACT defines the key.

Objects are merged recursively by key. Lists and scalar values (including `false`, `0` and explicit `null`) are atomic. If the highest-precedence layer defines a scalar/list where a lower layer defines an object, the higher layer owns the whole key and the lower structure is ignored.

## Provenance and conflicts

Resolution returns both:

- `effective`: the effective configuration;
- `provenance`: matching per-key source information;
- `conflicts`: paths where more than one layer supplied a value, with winner and shadowed sources.

This allows Controller APIs, audit logs and future Managed Configuration UI to explain why a customer value did or did not become effective.

## Relationship with P0-F

P0-G defines **who wins**. P0-F defines **what the canonical parameters mean**, their types, allowed values and mutability. The precedence resolver intentionally does not invent game-specific parameter semantics.
