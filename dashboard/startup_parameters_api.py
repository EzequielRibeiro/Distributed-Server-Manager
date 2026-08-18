"""Dashboard-facing startup parameter policy."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.runtime.startup_parameters import (
    build_effective_argv,
    normalize_startup_definition,
)


def startup_parameter_surface(
    definition: Mapping[str, Any],
    overrides: Mapping[str, Any] | None,
    role: str,
) -> dict[str, Any]:
    parameters = normalize_startup_definition(definition)
    overrides = dict(overrides or {})

    visible = []

    for parameter in parameters:
        if role in {"admin", "controller"}:
            allowed = True
        else:
            allowed = parameter.user_editable

        if not allowed:
            continue

        visible.append(
            {
                "id": parameter.id,
                "argument": parameter.argument,
                "default": parameter.default,
                "required": parameter.required,
                "user_editable": parameter.user_editable,
                "kind": parameter.kind,
                "override": overrides.get(parameter.id),
            }
        )

    return {
        "parameters": visible,
        "effective_argv": build_effective_argv(
            definition,
            overrides,
            allow_user_overrides=(
                role not in {"admin", "controller"}
            ),
        ),
    }
