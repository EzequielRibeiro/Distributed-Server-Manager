#!/usr/bin/env bash
# Capivara DSM - retired legacy content mutation compatibility entrypoint.
set -Eeuo pipefail

MESSAGE="Legacy content mutation is retired; use the Universal Content Platform (ContentAssignment/ContentRevision)."

if [[ "${DSM_OUTPUT_FORMAT:-human}" == "json" ]]; then
    if command -v jq >/dev/null 2>&1; then
        jq -nc --arg message "${MESSAGE}" '{error:"legacy_content_path_retired",message:$message}'
    else
        printf '{"error":"legacy_content_path_retired","message":"%s"}\n' "${MESSAGE}"
    fi
else
    printf '[DSM][CONTENT][RETIRED] %s\n' "${MESSAGE}" >&2
fi
exit 3
