# Capivara DSM 2.0.27

Patch release correcting the lifecycle of the local Agent used by Hybrid Controller installations.

## Fixed

- Added a first-class and safe `hybrid -> controller` demotion for the local Agent.
- Preserves the existing Controller and Node identities when the local Hybrid Agent is deactivated.
- Removes only local-Agent-owned registration/location state during demotion instead of deleting the shared Controller Node.
- Reconciles the local Agent configuration back to Controller mode after a successful persisted demotion.
- Restores the Dashboard action to activate the local Agent again after returning to Controller mode.
- Added a defensive guard preventing generic standalone-Agent removal from deleting a Node that is also owned by a Controller.

## Reliability

- Hybrid demotion is idempotent, including recovery when the local Agent registration is already absent.
- Added regression coverage for the complete `controller -> hybrid -> controller -> hybrid` lifecycle.
- Added regression coverage proving generic Agent removal preserves shared Agent/Node/Controller identity when the operation is invalid for Hybrid lifecycle.

## Compatibility

- No database schema changes relative to 2.0.26.
- No game catalog contract changes are introduced by this patch.
- Existing standalone Agent removal behavior remains unchanged for Nodes that are not shared with a Controller.
