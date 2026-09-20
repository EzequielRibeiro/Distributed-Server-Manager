# Capivara DSM 2.0.84

Customer server creation stability release.

## Runtime build selector

Fixes the Customer creation wizard when a dynamic runtime build request completes successfully but the interface remains stuck on `Carregando builds…`.

The runtime selector now keeps valid build responses for the currently selected runtime/version instead of discarding them only because an internal request generation changed.

## Create-server wizard event loop

Fixes a MutationObserver feedback loop around the disabled state of the Create Server button. The wizard now changes the disabled attribute only when a state transition is actually required, preventing repeated mutation callbacks from starving asynchronous UI continuations.

## Browser asset refresh

Updates the Customer page asset revisions for the runtime selector and create-server wizard so browsers load the corrected scripts immediately.

## Validation

Includes regression coverage for runtime build response handling and idempotent submit-state enforcement.
