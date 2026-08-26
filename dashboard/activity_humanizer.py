#!/usr/bin/env python3
"""Human-readable Portuguese summaries for semantic operator activities."""
from __future__ import annotations

from typing import Any, Mapping

_FIELD_LABELS = {
    "name": "nome",
    "legal_name": "razão social",
    "email": "e-mail",
    "phone": "telefone",
    "status": "status",
    "account_role": "perfil",
    "permission_profile": "permissão",
    "instance_limit": "limite de instâncias",
    "ends_at": "data de término",
    "resource_profile_id": "perfil de recursos",
    "interval_seconds": "intervalo",
    "retention_count": "retenção",
    "enabled": "estado do agendamento",
}


def actor_name(user: Mapping[str, Any] | None) -> str:
    actor = dict(user or {})
    return str(
        actor.get("display_name")
        or actor.get("name")
        or actor.get("username")
        or actor.get("id")
        or "Operador"
    ).strip()


def _display(value: Any) -> str:
    if value is None:
        return "não informado"
    if isinstance(value, bool):
        return "ativado" if value else "desativado"
    return str(value)


def describe_changes(changes: Mapping[str, Any] | None) -> str:
    descriptions: list[str] = []
    for field, raw in dict(changes or {}).items():
        label = _FIELD_LABELS.get(str(field), str(field).replace("_", " "))
        if not isinstance(raw, Mapping):
            continue
        if raw.get("changed") is True and "before" not in raw and "after" not in raw:
            descriptions.append(f"{label} foi alterado")
            continue
        before = raw.get("before")
        after = raw.get("after")
        if before == after:
            continue
        descriptions.append(
            f"{label} foi alterado de “{_display(before)}” para “{_display(after)}”"
        )
    if not descriptions:
        return ""
    if len(descriptions) == 1:
        return descriptions[0]
    return "; ".join(descriptions[:-1]) + " e " + descriptions[-1]


def humanize(
    action: str,
    *,
    user: Mapping[str, Any] | None,
    target_name: str | None = None,
    changes: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
) -> str:
    who = actor_name(user)
    target = str(target_name or "").strip()
    ctx = dict(context or {})
    action = str(action or "").strip().lower()

    if action == "auth.login":
        return f"{who} fez login no sistema."
    if action == "auth.logout":
        return f"{who} saiu do sistema."
    if action == "customer.created":
        return f"{who} criou o cadastro do cliente {target}."
    if action == "customer.updated":
        detail = describe_changes(changes)
        return f"{who} alterou o cadastro do cliente {target}." + (f" {detail}." if detail else "")
    if action == "customer.password_reset":
        return f"{who} redefiniu a senha de acesso de {target}."
    if action == "customer.contract.created":
        game = str(ctx.get("game_name") or ctx.get("game_id") or "serviço")
        return f"{who} criou um contrato de {game} para o cliente {target}."
    if action == "customer.member_role.updated":
        detail = describe_changes(changes)
        return f"{who} alterou o perfil de acesso de {target}." + (f" {detail}." if detail else "")
    if action == "customer.instance_access.updated":
        instance = str(ctx.get("instance_name") or ctx.get("instance_id") or "servidor")
        detail = describe_changes(changes)
        return f"{who} alterou o acesso de {target} ao servidor {instance}." + (f" {detail}." if detail else "")
    if action == "backup.schedule.created":
        instance = target or "servidor"
        return f"{who} agendou backups para o servidor {instance}."
    if action == "backup.schedule.updated":
        detail = describe_changes(changes)
        return f"{who} alterou o agendamento de backups do servidor {target}." + (f" {detail}." if detail else "")
    if action == "instance.started":
        return f"{who} iniciou o servidor {target}."
    if action == "instance.stopped":
        return f"{who} parou o servidor {target}."
    if action == "instance.restarted":
        return f"{who} reiniciou o servidor {target}."
    if action == "instance.deleted":
        return f"{who} excluiu o servidor {target}."

    resource = f" {target}" if target else ""
    return f"{who} executou a ação {action}{resource}."


__all__ = ["actor_name", "describe_changes", "humanize"]
