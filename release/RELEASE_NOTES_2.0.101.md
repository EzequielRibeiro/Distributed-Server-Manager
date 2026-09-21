# Capivara DSM 2.0.101

Java-runtime compatibility and Minecraft creation UX release.

## Fixes

- Discovers side-by-side Java installations on Linux and Windows Agents instead of treating only the default `java` executable as available.
- Placement evaluates all discovered Java majors against each RuntimeDefinition requirement, so a host with Java 21 and Java 25 can serve Java-21-only runtimes even when Java 25 is the system default.
- Selects the newest compatible JVM per runtime and exports the matching `JAVA_HOME` to the instance process.
- Launches Java `.jar` runtimes through the selected JVM with an explicit `-jar` invocation, including Minecraft Java Youer, Paper, Purpur, Vanilla and other jar-based runtimes.
- Preserves catalog-owned runtime engine and Java requirements in the distributed runtime policy so Agents cannot accidentally use an incompatible JVM.
- Bumps Linux and Windows Minecraft Java runtime profile versions so persisted specs reconcile to the new JVM-selection behavior.
- Clears stale version/build summary state immediately when switching Minecraft distributions, preventing the previous runtime version from remaining visible while a new version list is loading.

## Customer UI

- Adds richer responsive Minecraft runtime capability cards in the create-server wizard.
- Adds local vector icons for supported Minecraft distributions without external image dependencies.
- Keeps runtime selector assets explicitly cache-busted after the Java/runtime-selection changes.

## Validation

- PR #735 passed all 36 triggered workflows, including CI, Windows Agent Parity, Customer Geographic Placement, Agent Instance Runtime, M10 Final E2E Release Validation and External Controller Agent E2E.
- On `horizon-server`, Java discovery reports Java 21 and Java 25 concurrently while the default `java` remains Java 25.
- A direct Youer placement simulation with `min=21,max=21` is eligible on that host and the generated runtime policy selects `/usr/lib/jvm/java-21-openjdk-amd64/bin/java` with `JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64`.
- Before release preparation, there were no open pull requests and no remote branches containing commits not merged into `main`.
