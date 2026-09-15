# Capivara DSM 2.0.55

Maintenance release focused on the distributed administrative instance provisioning path.

## Highlights

- The administrative instance CLI now accepts the canonical public Customer reference `CLI-NNNNNN` consistently.
- Customer references are resolved once at the CLI boundary and converted to the internal numeric Customer primary key for repository operations.
- Controller lookup, owner lookup and instance creation now use the same normalized Customer identity instead of conflicting public/internal formats.
- JSON output preserves the public Customer code while internal persistence continues to use numeric foreign keys.
- Owner fallback handling is safe for numeric Customer primary keys.

## Included changes

- PR #516 — normalize Customer references in `instance_admin_cli.py` and remove the contradictory `--customer 1` / `--customer CLI-NNNNNN` behavior.

## Compatibility and scope

- No database migration is required.
- No Agent protocol change is required.
- This release is intended to unblock the distributed Bedrock provisioning E2E on Node1 after the 2.0.54 port-inventory fix.
