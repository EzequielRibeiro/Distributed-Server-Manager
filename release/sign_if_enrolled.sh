#!/usr/bin/env bash
# #928 official provenance. Never export the publisher private key to artifacts.
set -euo pipefail
COMMIT="${1:?approved commit}"
DIST="${2:?release output dir}"

case "${CAPIVARA_REQUIRE_SIGNED_PROVENANCE:-false}" in
    false)
        echo "Publisher provenance not enrolled; compatible no-drain remains blocked."
        exit 0
        ;;
    true) ;;
    *)
        echo "Invalid release signing enrollment flag." >&2
        exit 2
        ;;
esac

[[ "${COMMIT}" =~ ^[0-9a-f]{40}$ ]] || {
    echo "Release commit was not independently pinned." >&2
    exit 2
}
[[ "${CAPIVARA_SIGNING_KEY_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] || {
    echo "Release signer public-key SHA256 pin must be enrolled separately." >&2
    exit 2
}
[[ -n "${CAPIVARA_SIGNING_KEY_PEM:-}" ]] || {
    echo "Protected publisher private key has not been provided." >&2
    exit 2
}
[[ -n "${RUNNER_TEMP:-}" && -d "${RUNNER_TEMP}" && ! -L "${RUNNER_TEMP}" ]] || {
    echo "Safe ephemeral signing workspace unavailable." >&2
    exit 2
}
VERSION="$(tr -d '\r\n' < version)"
[[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+][A-Za-z0-9._-]+)?$ ]] || exit 2
DIST="$(realpath -e -- "${DIST}")"

umask 077
SIGNING_TMP="$(mktemp "${RUNNER_TEMP}/dsm928-publisher-key.XXXXXXXX")"
cleanup_key() { rm -f -- "${SIGNING_TMP}"; }
trap cleanup_key EXIT HUP INT TERM
printf '%s\n' "${CAPIVARA_SIGNING_KEY_PEM}" >"${SIGNING_TMP}"
unset CAPIVARA_SIGNING_KEY_PEM

python3 release/sign_official_release.py \
    --archive "${DIST}/capivara-dsm-${VERSION}.tar.gz" \
    --manifest "${DIST}/capivara-dsm-${VERSION}.manifest.json" \
    --commit "${COMMIT}" \
    --private-key "${SIGNING_TMP}" \
    --public-key-sha256 "${CAPIVARA_SIGNING_KEY_SHA256}"

echo "Release provenance sidecars generated; production no-drain NOT authorized."
