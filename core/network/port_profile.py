
"""Runtime-declared network port profile."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


_NAME_RE = re.compile(
    r"^[a-z][a-z0-9_]{0,63}$"
)


@dataclass(frozen=True)
class PortRequirement:
    name: str
    protocol: str
    offset: int
    bind_address: str = "0.0.0.0"


@dataclass(frozen=True)
class NetworkApplication:
    kind: str
    template: str | None = None
    file: str | None = None
    key: str | None = None
    value: str | None = None
    port: str | None = None
    derived_from: str | None = None


@dataclass(frozen=True)
class PortProfile:
    allocation: str
    block_size: int
    ports: tuple[PortRequirement, ...]
    applications: tuple[NetworkApplication, ...] = ()

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any] | None,
    ) -> "PortProfile | None":
        if raw is None:
            return None

        if not isinstance(raw, Mapping):
            raise ValueError(
                "network profile must be an object"
            )

        allocation = str(
            raw.get(
                "allocation",
                "block",
            )
        ).strip().lower()

        if allocation != "block":
            raise ValueError(
                "unsupported network allocation mode"
            )

        try:
            block_size = int(
                raw.get(
                    "block_size",
                    1,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "network block_size must be an integer"
            ) from exc

        if not 1 <= block_size <= 65535:
            raise ValueError(
                "network block_size is outside valid range"
            )

        raw_ports = raw.get("ports")

        if (
            not isinstance(raw_ports, list)
            or not raw_ports
        ):
            raise ValueError(
                "network profile requires at least one port"
            )

        ports: list[PortRequirement] = []
        names: set[str] = set()
        has_anchor = False

        for item in raw_ports:
            if not isinstance(item, Mapping):
                raise ValueError(
                    "network port definition must be an object"
                )

            name = str(
                item.get(
                    "name",
                    "",
                )
            ).strip().lower()

            if not _NAME_RE.fullmatch(name):
                raise ValueError(
                    f"invalid network port name: {name}"
                )

            if name in names:
                raise ValueError(
                    f"duplicate network port name: {name}"
                )

            protocol = str(
                item.get(
                    "protocol",
                    "",
                )
            ).strip().lower()

            if protocol not in {
                "tcp",
                "udp",
            }:
                raise ValueError(
                    f"invalid network protocol: {protocol}"
                )

            try:
                offset = int(
                    item.get(
                        "offset",
                        0,
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid port offset for {name}"
                ) from exc

            if not 0 <= offset <= 65534:
                raise ValueError(
                    f"invalid port offset for {name}"
                )

            bind_address = str(
                item.get(
                    "bind_address",
                    "0.0.0.0",
                )
            ).strip()

            if not bind_address:
                raise ValueError(
                    f"empty bind address for {name}"
                )

            names.add(name)

            if offset == 0:
                has_anchor = True

            ports.append(
                PortRequirement(
                    name=name,
                    protocol=protocol,
                    offset=offset,
                    bind_address=bind_address,
                )
            )

        if not has_anchor:
            raise ValueError(
                "network profile requires an offset 0 port"
            )

        max_offset = max(
            port.offset
            for port in ports
        )

        if max_offset >= block_size:
            raise ValueError(
                "network port offset must fit inside block_size"
            )

        applications: list[
            NetworkApplication
        ] = []

        raw_apply = raw.get(
            "apply",
            [],
        )

        if not isinstance(raw_apply, list):
            raise ValueError(
                "network apply must be an array"
            )

        for item in raw_apply:
            if not isinstance(item, Mapping):
                raise ValueError(
                    "network apply entry must be an object"
                )

            kind = str(
                item.get(
                    "kind",
                    "",
                )
            ).strip().lower()

            if kind == "argument":
                template = str(
                    item.get(
                        "template",
                        "",
                    )
                )

                if not template:
                    raise ValueError(
                        "argument network application "
                        "requires template"
                    )

                applications.append(
                    NetworkApplication(
                        kind=kind,
                        template=template,
                    )
                )

            elif kind == "property":
                file = str(
                    item.get(
                        "file",
                        "",
                    )
                ).strip()

                key = str(
                    item.get(
                        "key",
                        "",
                    )
                ).strip()

                value = str(
                    item.get(
                        "value",
                        "",
                    )
                )

                if not file or not key:
                    raise ValueError(
                        "property network application "
                        "requires file and key"
                    )

                applications.append(
                    NetworkApplication(
                        kind=kind,
                        file=file,
                        key=key,
                        value=value,
                    )
                )

            elif kind == "derived":
                port = str(item.get("port", "")).strip().lower()
                derived_from = str(item.get("from", "")).strip().lower()
                if port not in names or derived_from not in names or port == derived_from:
                    raise ValueError("derived network application requires valid port and from roles")
                applications.append(NetworkApplication(kind=kind, port=port, derived_from=derived_from))

            else:
                raise ValueError(
                    f"unsupported network application: {kind}"
                )

        if "apply" in raw:
            referenced: set[str] = set()
            for application in applications:
                if application.kind == "derived" and application.port:
                    referenced.add(application.port)
                    continue
                source = application.template if application.kind == "argument" else application.value
                referenced.update(re.findall(r"\{([a-z][a-z0-9_]{0,63})\}", source or ""))
            unknown = referenced - names
            if unknown:
                raise ValueError("network application references unknown ports: " + ", ".join(sorted(unknown)))
            unused = names - referenced
            if unused:
                raise ValueError("network ports are reserved but not applied: " + ", ".join(sorted(unused)))

        return cls(
            allocation=allocation,
            block_size=block_size,
            ports=tuple(ports),
            applications=tuple(applications),
        )

    @property
    def protocols(self) -> set[str]:
        return {
            port.protocol
            for port in self.ports
        }

    @property
    def names(self) -> set[str]:
        return {
            port.name
            for port in self.ports
        }
