#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(
    cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
    pwd
)"

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

log_error()
{
    :
}

DSM_ROOT="${ROOT}"

# shellcheck source=../update-manager/verify-release.sh
source "${ROOT}/update-manager/verify-release.sh"

VERIFY_CHECKSUM=1

TEST_ROOT="$(mktemp -d)"

cleanup()
{
    rm -rf -- "${TEST_ROOT}"
    rm -rf -- /tmp/dsm-verify
}

trap cleanup EXIT


create_archive()
{
    local archive="$1"
    local mode="$2"

    python3 - "${archive}" "${mode}" <<'PY'
import io
import sys
import tarfile

archive_path = sys.argv[1]
mode = sys.argv[2]

root = "capivara-dsm-1.2.3"


def add_file(tar, name, data=b"test\n"):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def add_symlink(tar, name, target):
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    tar.addfile(info)


def add_hardlink(tar, name, target):
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE
    info.linkname = target
    tar.addfile(info)


with tarfile.open(archive_path, "w:gz") as tar:
    add_file(tar, f"{root}/version", b"1.2.3\n")
    add_file(tar, f"{root}/bin/dsm", b"#!/usr/bin/env bash\n")
    add_file(
        tar,
        f"{root}/core/bootstrap.sh",
        b"#!/usr/bin/env bash\n",
    )

    if mode == "valid":
        add_file(tar, f"{root}/config/file..txt")

    elif mode == "traversal":
        add_file(tar, f"{root}/../../escape.txt")

    elif mode == "absolute":
        add_file(tar, "/tmp/capivara-escape.txt")

    elif mode == "safe-symlink":
        add_file(tar, f"{root}/data/target.txt")
        add_symlink(
            tar,
            f"{root}/data/link.txt",
            "target.txt",
        )

    elif mode == "absolute-symlink":
        add_symlink(
            tar,
            f"{root}/data/link.txt",
            "/tmp/capivara-escape.txt",
        )

    elif mode == "escaping-symlink":
        add_symlink(
            tar,
            f"{root}/data/link.txt",
            "../../../outside.txt",
        )

    elif mode == "safe-hardlink":
        add_file(tar, f"{root}/data/target.txt")
        add_hardlink(
            tar,
            f"{root}/data/link.txt",
            f"{root}/data/target.txt",
        )

    elif mode == "absolute-hardlink":
        add_hardlink(
            tar,
            f"{root}/data/link.txt",
            "/tmp/capivara-escape.txt",
        )

    elif mode == "traversal-hardlink":
        add_hardlink(
            tar,
            f"{root}/data/link.txt",
            "../../outside.txt",
        )

    elif mode == "two-roots":
        add_file(
            tar,
            "capivara-dsm-2.0.0/extra.txt",
        )

    elif mode == "invalid-root":
        add_file(
            tar,
            "capivara-dsm-invalid/extra.txt",
        )

    else:
        raise SystemExit(f"unknown archive mode: {mode}")
PY
}


verify_accepts()
{
    local mode="$1"
    local archive="${TEST_ROOT}/${mode}.tar.gz"
    local checksum

    create_archive "${archive}" "${mode}"

    checksum="$(
        sha256sum "${archive}" |
        awk '{print $1}'
    )"

    if ! verify_release \
        "${archive}" \
        "${checksum}" \
        >/dev/null 2>&1
    then
        fail "valid archive rejected: ${mode}"
    fi

    echo "PASS: accepted ${mode}"
}


verify_rejects()
{
    local mode="$1"
    local archive="${TEST_ROOT}/${mode}.tar.gz"
    local checksum

    create_archive "${archive}" "${mode}"

    checksum="$(
        sha256sum "${archive}" |
        awk '{print $1}'
    )"

    if verify_release \
        "${archive}" \
        "${checksum}" \
        >/dev/null 2>&1
    then
        fail "unsafe archive accepted: ${mode}"
    fi

    echo "PASS: rejected ${mode}"
}


echo "===== Release Archive Security ====="

verify_accepts valid
verify_accepts safe-symlink
verify_accepts safe-hardlink

verify_rejects traversal
verify_rejects absolute
verify_rejects absolute-symlink
verify_rejects escaping-symlink
verify_rejects absolute-hardlink
verify_rejects traversal-hardlink
verify_rejects two-roots
verify_rejects invalid-root

echo
echo "Archive security tests passed."
