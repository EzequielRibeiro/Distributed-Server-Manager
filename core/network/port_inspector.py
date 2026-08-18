
"""Operating-system network port inspection."""

from __future__ import annotations

import re
import subprocess


class PortInspectionError(RuntimeError):
    pass


class LocalPortInspector:
    """
    Linux/local implementation.

    Remote Agents will later implement the same contract through
    Controller <-> Agent communication.
    """

    def occupied(
        self,
        protocol: str,
        start_port: int,
        end_port: int,
    ) -> set[int]:
        protocol = protocol.strip().lower()

        if protocol == "udp":
            command = [
                "ss",
                "-H",
                "-lun",
            ]
        elif protocol == "tcp":
            command = [
                "ss",
                "-H",
                "-ltn",
            ]
        else:
            raise ValueError(
                f"unsupported protocol: {protocol}"
            )

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (
            OSError,
            subprocess.SubprocessError,
        ) as exc:
            raise PortInspectionError(
                "unable to inspect operating-system ports"
            ) from exc

        if result.returncode != 0:
            raise PortInspectionError(
                "unable to inspect operating-system ports"
            )

        ports: set[int] = set()

        for line in result.stdout.splitlines():
            for field in line.split():
                match = re.search(
                    r":([0-9]+)$",
                    field,
                )

                if not match:
                    continue

                port = int(
                    match.group(1)
                )

                if (
                    start_port
                    <= port
                    <= end_port
                ):
                    ports.add(port)
                    break

        return ports


class RemoteAgentPortInspector:
    """
    Contract placeholder.

    It deliberately fails closed until the Controller <-> Agent
    transport exposes a trustworthy socket inspection endpoint.
    """

    def occupied(
        self,
        protocol: str,
        start_port: int,
        end_port: int,
    ) -> set[int]:
        raise PortInspectionError(
            "remote Agent port inspection is not available"
        )
