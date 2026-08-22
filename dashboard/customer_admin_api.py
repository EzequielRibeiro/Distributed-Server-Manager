#!/usr/bin/env python3
"""Administrative API for Customer lifecycle, credentials, contracts and infrastructure views."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from admin_infrastructure_service import AdminInfrastructureService
from agent_runtime_repository import AgentRuntimeRepository
from customer_admin_repository import CustomerAdminRepository
from customer_mailer import send_temporary_password

CUSTOMER_ADMIN_COLLECTION = "/api/admin/customers"
CUSTOMER_ADMIN_DETAIL = "/api/admin/customer"
CUSTOMER_ADMIN_GAMES = "/api/admin/catalog/games"
CUSTOMER_ADMIN_PASSWORD_RESET = "/api/admin/customer/password-reset"
CUSTOMER_ADMIN_CONTRACT = "/api/admin/customer/contracts"
CUSTOMER_ADMIN_MEMBER_ROLE = "/api/admin/customer/member-role"
CUSTOMER_ADMIN_ACCESS = "/api/admin/customer/access"
CUSTOMER_PASSWORD_CHANGE = "/api/customer/password/change-temporary"
ADMIN_INFRASTRUCTURE_OVERVIEW = "/api/admin/infrastructure/overview"
ADMIN_AGENT_DETAIL = "/api/admin/agent/detail"
CUSTOMER_ADMIN_GET_PATHS = {
    CUSTOMER_ADMIN_COLLECTION,
    CUSTOMER_ADMIN_DETAIL,
    CUSTOMER_ADMIN_GAMES,
    ADMIN_INFRASTRUCTURE_OVERVIEW,
    ADMIN_AGENT_DETAIL,
}
CUSTOMER_ADMIN_POST_PATHS = {
    CUSTOMER_ADMIN_COLLECTION,
    CUSTOMER_ADMIN_PASSWORD_RESET,
    CUSTOMER_ADMIN_CONTRACT,
    CUSTOMER_ADMIN_MEMBER_ROLE,
    CUSTOMER_ADMIN_ACCESS,
    CUSTOMER_PASSWORD_CHANGE,
}

ROOT_DIR = Path(__file__).resolve().parents[1]
CATALOG_GAMES_DIR = ROOT_DIR / "catalog" / "v2" / "games"
GAME_LABELS = {
    "arma3": "Arma 3",
    "dayz": "DayZ",
    "luanti": "Luanti",
    "mindustry": "Mindustry",
    "minecraft": "Minecraft",
    "rust": "Rust",
}


def _role(user: dict[str, Any] | None) -> str:
    return str((user or {}).get("role") or "")


def _admin_read(user: dict[str, Any] | None) -> bool:
    return _role(user) in {"admin", "controller", "operator"}


def _admin_write(user: dict[str, Any] | None) -> bool:
    return _role(user) in {"admin", "controller"}


def _catalog_games() -> list[dict[str, str]]:
    if not CATALOG_GAMES_DIR.is_dir():
        return []
    games: list[dict[str, str]] = []
    for path in sorted(CATALOG_GAMES_DIR.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or not (path / "runtimes").is_dir():
            continue
        game_id = path.name.strip().lower()
        if game_id:
            games.append({"id": game_id, "name": GAME_LABELS.get(game_id, game_id.replace("-", " ").title())})
    return games


def _deliver_temporary_password(email: str | None, username: str, password: str, *, reset: bool) -> bool:
    if not email:
        return False
    try:
        return bool(send_temporary_password(email, username, password, reset=reset))
    except Exception:
        return False


def _customer_detail(repository: CustomerAdminRepository, backend, customer_id: str) -> dict[str, Any]:
    detail = repository.detail(customer_id)
    runtime = AgentRuntimeRepository(backend)
    node_cache: dict[str, str | None] = {}
    for instance in detail.get("instances") or []:
        agent_id = str(instance.get("agent_id") or "").strip()
        if not agent_id:
            instance["node_id"] = None
            continue
        if agent_id not in node_cache:
            try:
                node_cache[agent_id] = runtime.snapshot(agent_id, refresh_health=False).get("node_id")
            except Exception:
                node_cache[agent_id] = None
        instance["node_id"] = node_cache[agent_id]
    return detail


def dispatch_customer_admin_get(path: str, query: dict[str, list[str]], *, user, backend):
    if path not in CUSTOMER_ADMIN_GET_PATHS:
        return None
    if not _admin_read(user):
        return 403, {"error": "access denied"}
    try:
        if path == CUSTOMER_ADMIN_GAMES:
            return 200, {"games": _catalog_games()}
        if path == ADMIN_INFRASTRUCTURE_OVERVIEW:
            return 200, AdminInfrastructureService(backend).overview(user)
        if path == ADMIN_AGENT_DETAIL:
            agent_id = str((query.get("agent_id") or [""])[0]).strip()
            return 200, AdminInfrastructureService(backend).agent_detail(user, agent_id)
        repository = CustomerAdminRepository(backend)
        if path == CUSTOMER_ADMIN_COLLECTION:
            term = str((query.get("q") or [""])[0])
            return 200, {"customers": repository.search(term)}
        customer_id = str((query.get("id") or [""])[0]).strip()
        if not customer_id:
            return 400, {"error": "customer id is required"}
        return 200, _customer_detail(repository, backend, customer_id)
    except PermissionError as exc:
        return 403, {"error": str(exc)}
    except ValueError as exc:
        return 404, {"error": str(exc)}
    except Exception:
        return 500, {"error": "administrative query failed"}


def dispatch_customer_admin_post(path: str, payload: dict[str, Any], *, user, backend):
    if path not in CUSTOMER_ADMIN_POST_PATHS:
        return None
    repository = CustomerAdminRepository(backend)
    try:
        if path == CUSTOMER_PASSWORD_CHANGE:
            if _role(user) != "customer":
                return 403, {"error": "access denied"}
            password = str(payload.get("password") or "")
            confirmation = str(payload.get("password_confirmation") or "")
            if password != confirmation:
                return 400, {"error": "password confirmation does not match"}
            repository.change_temporary_password(str(user.get("username") or ""), password)
            return 200, {"changed": True, "must_change_password": False}

        if not _admin_write(user):
            return 403, {"error": "administrative write access required"}

        if path == CUSTOMER_ADMIN_COLLECTION:
            email = str(payload.get("email") or "").strip() or None
            result = repository.create_customer(
                customer_id=str(payload.get("id") or ""),
                name=str(payload.get("name") or ""),
                username=str(payload.get("username") or ""),
                email=email,
                phone=(str(payload.get("phone") or "").strip() or None),
                controller_id=(str(payload.get("controller_id") or "").strip() or None),
            )
            result["delivered"] = _deliver_temporary_password(email, str(result["username"]), str(result["temporary_password"]), reset=False)
            return 201, result

        if path == CUSTOMER_ADMIN_PASSWORD_RESET:
            username = str(payload.get("username") or "")
            matches = repository.search(username); email = None
            for customer in matches:
                if any(str(member.get("username")) == username.lower() for member in customer.get("users", [])):
                    email = customer.get("email"); break
            result = repository.reset_password(username)
            result["delivered"] = _deliver_temporary_password(email, str(result["username"]), str(result["temporary_password"]), reset=True)
            return 200, result

        if path == CUSTOMER_ADMIN_CONTRACT:
            limit = int(payload.get("instance_limit") or 1)
            game_id = str(payload.get("game_id") or "").strip().lower()
            if game_id not in {item["id"] for item in _catalog_games()}:
                raise ValueError("game is not available in Catalog v2")
            result = repository.create_contract(
                customer_id=str(payload.get("customer_id") or ""), game_id=game_id, instance_limit=limit,
                contract_id=(str(payload.get("id") or "").strip() or None),
                ends_at=(str(payload.get("ends_at") or "").strip() or None),
            )
            return 201, result

        if path == CUSTOMER_ADMIN_MEMBER_ROLE:
            repository.set_member_role(str(payload.get("customer_id") or ""), str(payload.get("username") or ""), str(payload.get("account_role") or ""))
            return 200, {"updated": True}

        if path == CUSTOMER_ADMIN_ACCESS:
            profile = str(payload.get("permission_profile") or "").strip() or None
            repository.set_instance_access(str(payload.get("customer_id") or ""), str(payload.get("username") or ""), str(payload.get("instance_id") or ""), profile)
            return 200, {"updated": True}
    except (ValueError, TypeError) as exc:
        return 400, {"error": str(exc)}
    except Exception:
        return 500, {"error": "customer administration operation failed"}
    return 404, {"error": "not found"}


__all__ = [
    "ADMIN_AGENT_DETAIL", "ADMIN_INFRASTRUCTURE_OVERVIEW",
    "CUSTOMER_ADMIN_GET_PATHS", "CUSTOMER_ADMIN_POST_PATHS",
    "CUSTOMER_PASSWORD_CHANGE", "dispatch_customer_admin_get", "dispatch_customer_admin_post",
]
