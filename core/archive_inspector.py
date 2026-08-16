#!/usr/bin/env python3

"""
Capivara Distributed Server Manager

Read TAR archive metadata without extracting the archive.

Output format:

    type<TAB>member<TAB>target

Types:
    member
    symlink
    hardlink

The output is intended to be consumed by the shell archive-security
helpers. This module performs metadata inspection only. It does not
extract archive contents and does not decide whether a path is safe.
"""

from __future__ import annotations

import sys
import tarfile


def inspect_archive(path: str) -> int:
    try:
        with tarfile.open(path, mode="r:*") as archive:
            for item in archive:
                if item.issym():
                    item_type = "symlink"
                    target = item.linkname
                elif item.islnk():
                    item_type = "hardlink"
                    target = item.linkname
                else:
                    item_type = "member"
                    target = ""

                sys.stdout.write(
                    f"{item_type}\t{item.name}\t{target}\n"
                )

    except (OSError, tarfile.TarError) as exc:
        print(
            f"archive inspection failed: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: archive_inspector.py ARCHIVE",
            file=sys.stderr,
        )
        return 2

    return inspect_archive(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
