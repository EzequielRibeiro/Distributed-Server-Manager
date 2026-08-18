#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOWNLOAD_MODULE="${ROOT}/update-manager/download-release.sh"

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

SOURCE_DIR="${TMP_DIR}/source"
TEST_DOWNLOAD_DIR="${TMP_DIR}/downloads"
TEST_CHECKSUM_DIR="${TMP_DIR}/checksums"
PACKAGE_SOURCE="${TMP_DIR}/capivara-dsm-test.tar.gz"
CHECKSUM_SOURCE="${TMP_DIR}/capivara-dsm-test.tar.gz.sha256"

mkdir -p \
    "${SOURCE_DIR}/capivara-dsm-test" \
    "${TEST_DOWNLOAD_DIR}" \
    "${TEST_CHECKSUM_DIR}"

printf '%s\n' 'test' >"${SOURCE_DIR}/capivara-dsm-test/version"
tar -czf "${PACKAGE_SOURCE}" -C "${SOURCE_DIR}" capivara-dsm-test
sha256sum "${PACKAGE_SOURCE}" >"${CHECKSUM_SOURCE}"

DSM_ROOT="${ROOT}"
export DSM_ROOT

# shellcheck source=../update-manager/download-release.sh
source "${DOWNLOAD_MODULE}"

# Override cache paths after loading the production configuration.
DOWNLOAD_DIR="${TEST_DOWNLOAD_DIR}"
CHECKSUM_DIR="${TEST_CHECKSUM_DIR}"
DOWNLOAD_TIMEOUT=5

log_error()
{
    printf '[ERROR] %s\n' "$*" >&2
}

curl()
{
    local OUTPUT=""
    local URL=""

    while [[ $# -gt 0 ]]
    do
        case "$1" in
            --output)
                OUTPUT="$2"
                shift 2
                ;;
            --fail|--location)
                shift
                ;;
            --connect-timeout)
                shift 2
                ;;
            *)
                URL="$1"
                shift
                ;;
        esac
    done

    [[ -n "${OUTPUT}" ]] || return 2
    [[ -n "${URL}" ]] || return 2

    case "${URL}" in
        *.tar.gz.sha256)
            cp -- "${CHECKSUM_SOURCE}" "${OUTPUT}"
            ;;
        *.tar.gz)
            cp -- "${PACKAGE_SOURCE}" "${OUTPUT}"
            ;;
        *)
            return 22
            ;;
    esac
}

RELEASE_URL="https://example.invalid/capivara-dsm-test.tar.gz"
EXPECTED_PACKAGE="${TEST_DOWNLOAD_DIR}/capivara-dsm-test.tar.gz"
RELEASE_STDERR="${TMP_DIR}/release.stderr"

PACKAGE="$(download_release "${RELEASE_URL}" 2>"${RELEASE_STDERR}")"

[[ "${PACKAGE}" == "${EXPECTED_PACKAGE}" ]] \
    || fail "download_release stdout contains data other than the package path: ${PACKAGE}"

[[ -f "${PACKAGE}" ]] \
    || fail "download_release returned a path that is not a file"

grep -q '^Baixando release DSM:$' "${RELEASE_STDERR}" \
    || fail "release progress message was not written to stderr"

grep -Fq "${RELEASE_URL}" "${RELEASE_STDERR}" \
    || fail "release URL was not written to stderr"

CHECKSUM_URL="https://example.invalid/capivara-dsm-test.tar.gz.sha256"
EXPECTED_CHECKSUM="${TEST_CHECKSUM_DIR}/capivara-dsm-test.tar.gz.sha256"
CHECKSUM_STDERR="${TMP_DIR}/checksum.stderr"

CHECKSUM_FILE="$(download_checksum "${CHECKSUM_URL}" 2>"${CHECKSUM_STDERR}")"

[[ "${CHECKSUM_FILE}" == "${EXPECTED_CHECKSUM}" ]] \
    || fail "download_checksum stdout contains data other than the checksum path: ${CHECKSUM_FILE}"

[[ -s "${CHECKSUM_FILE}" ]] \
    || fail "download_checksum returned an empty or missing file"

grep -q '^Baixando checksum SHA256:$' "${CHECKSUM_STDERR}" \
    || fail "checksum progress message was not written to stderr"

grep -Fq "${CHECKSUM_URL}" "${CHECKSUM_STDERR}" \
    || fail "checksum URL was not written to stderr"

# Cached files must preserve the same stdout-only return contract.
CACHE_STDERR="${TMP_DIR}/cache.stderr"
CACHED_PACKAGE="$(download_release "${RELEASE_URL}" 2>"${CACHE_STDERR}")"

[[ "${CACHED_PACKAGE}" == "${EXPECTED_PACKAGE}" ]] \
    || fail "cached download_release result changed its stdout contract"

[[ ! -s "${CACHE_STDERR}" ]] \
    || fail "cached download_release unexpectedly emitted progress output"

printf '%s\n' 'Update download output contract tests passed.'
