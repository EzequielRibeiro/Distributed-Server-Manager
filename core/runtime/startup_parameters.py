"""Structured startup parameters and per-instance overrides."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class StartupParameterError(ValueError):
    pass


@dataclass(frozen=True)
class StartupParameter:
    id: str
    argument: str
    default: Any = None
    required: bool = False
    user_editable: bool = False
    kind: str = "value"


def normalize_startup_definition(
    definition: Mapping[str, Any],
) -> tuple[StartupParameter, ...]:
    process = definition.get("process", {})

    if not isinstance(process, Mapping):
        raise StartupParameterError(
            "process definition must be an object"
        )

    raw = process.get("parameters", [])

    if raw is None:
        raw = []

    if not isinstance(raw, list):
        raise StartupParameterError(
            "process.parameters must be an array"
        )

    result: list[StartupParameter] = []
    ids: set[str] = set()

    for item in raw:
        if not isinstance(item, Mapping):
            raise StartupParameterError(
                "startup parameter must be an object"
            )

        parameter_id = str(item.get("id", "")).strip().lower()

        if not _ID_RE.fullmatch(parameter_id):
            raise StartupParameterError(
                f"invalid startup parameter id: {parameter_id}"
            )

        if parameter_id in ids:
            raise StartupParameterError(
                f"duplicate startup parameter: {parameter_id}"
            )

        argument = str(item.get("argument", "")).strip()

        if not argument:
            raise StartupParameterError(
                f"parameter {parameter_id} has no argument"
            )

        kind = str(item.get("kind", "value")).strip().lower()

        if kind not in {"value", "flag"}:
            raise StartupParameterError(
                f"unsupported parameter kind: {kind}"
            )

        ids.add(parameter_id)

        result.append(
            StartupParameter(
                id=parameter_id,
                argument=argument,
                default=item.get("default"),
                required=bool(item.get("required", False)),
                user_editable=bool(
                    item.get("user_editable", False)
                ),
                kind=kind,
            )
        )

    return tuple(result)


def build_effective_argv(
    definition: Mapping[str, Any],
    overrides: Mapping[str, Any] | None = None,
    *,
    allow_user_overrides: bool = False,
) -> list[str]:
    parameters = normalize_startup_definition(definition)
    overrides = overrides or {}

    known = {parameter.id for parameter in parameters}

    unknown = set(overrides) - known

    if unknown:
        raise StartupParameterError(
            "unknown startup parameter override: "
            + ", ".join(sorted(unknown))
        )

    argv: list[str] = []

    for parameter in parameters:
        has_override = parameter.id in overrides

        if has_override and (
            not allow_user_overrides
            and parameter.user_editable
        ):
            value = overrides[parameter.id]
        elif has_override:
            value = overrides[parameter.id]
        else:
            value = parameter.default

        if parameter.required and value in {None, ""}:
            raise StartupParameterError(
                f"required startup parameter is missing: "
                f"{parameter.id}"
            )

        if parameter.kind == "flag":
            if bool(value):
                argv.append(parameter.argument)
            continue

        if value is None:
            continue

        rendered = parameter.argument.format(value=value)
        argv.append(rendered)

    process = definition.get("process", {})
    base_args = process.get("args", [])

    if isinstance(base_args, str):
        base_args = [base_args] if base_args else []

    if not isinstance(base_args, list):
        raise StartupParameterError(
            "process.args must be a string or array"
        )

    return [str(item) for item in base_args] + argv
