# Capivara DSM 2.0.56

Platform release that publishes the completed Universal Content Platform + Minecraft roadmap and the new low-latency distributed game console path.

## Highlights

- Universal Content Platform is now the single operational authority for managed mods, plugins, modpacks, Workshop content and external uploads. The final U11 cleanup retires the old `/api/mods` and `cap mods` surfaces, removes legacy catalog mutation paths and blocks File Manager writes into Agent-owned managed-content projections.
- Minecraft managed content is fully integrated with runtime capabilities, Modrinth/CurseForge resolution, composed modpack bundles, YARA-X security gates, immutable revisions, update/rollback orchestration and Linux/Windows E2E parity.
- Customer instance owner lookup now consistently uses the canonical `customer_id` relationship instead of the wrong owner column.
- Administrative provisioning now resolves the canonical RuntimeSelection server-side before queueing the Agent job. Dynamic runtimes such as Minecraft Bedrock carry their resolved artifact URL, version and build to the Agent instead of sending an incomplete static provider definition.
- The customer/controller console now streams live output over SSE with safe ANSI rendering and semantic fallback coloring instead of relying on fixed browser polling.
- Linux Agents push restricted instance journal output to the Controller over an authenticated outbound chunked HTTP stream. The main Agent remains unprivileged with respect to the system journal; a dedicated root helper exposes only `capivara-instance-*.service` output through a protected Unix socket.
- Windows Agents now have console push parity: new lines from the managed `windows-process` log are tailed locally and sent through the same authenticated chunked/NDJSON protocol, while heartbeat snapshots remain the fallback.

## Included changes

- PR #523 — retire legacy managed-content paths and complete U11/UCP migration.
- PR #521 — fix instance owner lookup to use `customer_id` consistently.
- PR #522 — add live SSE console output with safe ANSI rendering and polling fallback.
- PR #524 — push Linux Agent instance journal output to the Controller with restricted journal access, cursor deduplication and ownership validation.
- PR #526 — resolve dynamic runtime selection before administrative instance provisioning and fail closed when a resolved HTTP artifact URL is missing.
- PR #527 — add Windows Agent live-console push parity with managed-log tailing, heartbeat fallback and path containment.
- PR #529 — make administrative provisioning derive requirements and runtime policy from the canonical catalog definition before placement/provisioning.
- PR #530 — authorize the Customer live-runtime console asset in the canonical authenticated static-asset policy.
- PR #531 — allow privileged runtime seeding from the canonical Agent game-data root while retaining path-containment and copy-once safeguards.
- PR #532 — stream console lines event-driven from journald/Agent push to SSE clients without Controller polling, with cursor continuity and heartbeat fallback.

## Compatibility and scope

- No new database baseline migration is required by this release.
- The 2.0.56 publication remains gated on the live distributed provisioning E2E for the runtime-selection fix; release metadata may be prepared and CI-validated before that operational proof, but the release must not be merged/published until it passes.
- Linux Agents should be updated to 2.0.56 to use the new low-latency journal push path and restricted `capivara-agent-console-reader.service`; older Agents continue to rely on the existing console snapshot/fallback path until upgraded.
- Windows Agents should be updated to 2.0.56 to use live push from the managed `windows-process` log. No additional Windows service or inbound port is introduced; the existing heartbeat console snapshot remains the fallback.
- Legacy `content_installations` schema may remain as non-authoritative historical residue, but no active Dashboard/API/CLI path can mutate managed content through it.
- The release preserves the fail-closed U7 security model and the U9 rollback contract: rejected candidate content does not replace the last clean applied revision.
