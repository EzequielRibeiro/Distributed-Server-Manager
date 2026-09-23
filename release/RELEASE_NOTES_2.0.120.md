# Capivara DSM 2.0.120

## Customer visuals and native Steam Query

This release improves the Customer experience for runtime selection, managed content discovery, and public server verification.

### Customer interface

- Renders runtime card icons inline so they remain visible on mobile browsers without relying on an external SVG sprite reference.
- Proxies Modrinth and CurseForge catalog images through an authenticated same-origin Controller endpoint while preserving the strict Dashboard CSP.
- Restricts proxied images to approved HTTPS CDN hosts, validates redirects and MIME types, and enforces a 4 MiB response limit.

### Native Steam / Valve query

- Adds a native stdlib Steam A2S client in the Controller.
- Valve-compatible games now use a native `Testar Steam Query` action in the Customer connection card.
- The native test validates A2S_INFO and A2S_RULES and reports server name, map, player counts, version, and published rule data.
- DayZ query uses the actual reserved Steam query port.
- Non-Valve games retain the existing external public checker path.

## Validation

- PR #805: customer visuals, catalog image proxy, and native Steam query.
- The final PR revision completed 31/31 GitHub checks successfully.
- Linux and Windows final E2E, CI Gate, Release Readiness, database isolated deployment gates, customer distributed E2E, and Agent public network all passed.
