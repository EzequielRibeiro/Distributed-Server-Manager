# Capivara DSM 2.0.116

## Customer content security feedback and Minecraft contract selection

This release improves the Customer workspace in two related areas: selecting the intended Minecraft product contract and keeping uploaded content security state synchronized without requiring a manual page refresh.

### Minecraft contract selection

- Distinguishes Minecraft Padrão and Minecraft Modificado when more than one active Minecraft contract exists for the same customer.
- Stops silently selecting the first available contract for a game.
- Keeps direct-open behavior when only one eligible contract exists.
- Preserves backend enforcement of allowed runtime IDs from the selected contract.

### Live content security scan status

- Keeps content status live after external file upload while the Agent/YARA-X security scan is still running.
- Adds a temporary 2.5 second watchdog refresh for transient content states even when the SSE stream is connected.
- Displays an animated `Verificando segurança…` badge while content is pending/unscanned.
- Stops the temporary polling when content reaches a terminal state.
- Shows immediate customer feedback when content transitions to blocked or when the security scan fails.
- Preserves the existing SSE content stream as the primary low-latency update path.
- Respects `prefers-reduced-motion` for the scan animation.

## Validation

- PR #791: disambiguate Minecraft contract selection.
- PR #792: keep Customer content security scan status live and add animated scanning feedback.
- All triggered PR checks for #792 passed.
- The post-merge `main` validation for #792 completed 33 workflows successfully, including CI, Customer Instance Workspace v2, Final Customer Distributed E2E, Capivara 2.0 Release Readiness, M8 Universal Mod Management, M9 Minecraft Modpacks, Universal Server Update, and related catalog/runtime gates.
