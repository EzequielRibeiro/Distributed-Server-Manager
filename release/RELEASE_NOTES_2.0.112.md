# Capivara DSM 2.0.112

## Console command history lifecycle and UI

The game console now separates live runtime output from persisted command-response history and resets that history when the instance is successfully restarted.

### Improvements

- Adds a collapsed **Exibir histórico de comandos** panel to Customer and Controller instance views.
- Shows the number of stored command-response lines in the history control.
- Keeps live systemd journal / Agent SSE output in the primary console surface.
- Renders persisted command responses in a dedicated history surface.
- Improves wrapping of long console lines on narrow/mobile layouts.

### Lifecycle behavior

- A successful instance `restart` clears persisted command-response history for that instance.
- `start` and `stop` do not clear command history.
- Cleanup is scoped to the restarted instance only.
- Live journal/SSE transport remains unchanged.

### Validation

- PR #770 passed all required GitHub checks before merge.
- Repository regression coverage verifies instance-scoped history cleanup.
- UI regression coverage verifies the collapsible history controls.
- Current-session journal scoping from 2.0.111 remains intact.
