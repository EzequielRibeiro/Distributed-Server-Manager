# Capivara DSM 2.0.87

Minecraft Java HTTP installer hotfix.

## Installer artifact preservation

Fixes Forge, NeoForge and Quilt provisioning failures in the Agent game-data install stage with:

`installer artifact is missing`

Typed Java installer JARs are ZIP containers by format. The HTTP provider previously auto-detected them as archives and extracted their contents instead of preserving the installer JAR expected by the typed installer.

Linux and Windows Agents now preserve the downloaded artifact when the runtime declares a typed `java_jar` or `quilt_server` installer, while normal archives continue to be extracted.

## Validation

Includes a regression using a structurally valid ZIP/JAR artifact and coverage for the Windows preservation path.
