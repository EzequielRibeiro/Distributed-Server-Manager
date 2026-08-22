#!/usr/bin/env python3
# =============================================================
# DSM Dashboard
#
# Arquivo: dashboard/server.py
# File: dashboard/server.py
#
# Servidor HTTP Dashboard DSM
# DSM Dashboard HTTP Server
# =============================================================

import os
import sys
import json
import time

# =============================================================
# Requisitos de Versão | Version Requirements
# =============================================================
if sys.version_info < (3, 9):
    print("ERRO: O Dashboard requer Python 3.9 ou superior.")
    print("ERROR: Dashboard requires Python 3.9 or higher.")
    sys.exit(1)

import base64
import binascii
import mimetypes
import re
import subprocess
import threading
import tempfile
import sqlite3
import shutil
import tarfile
import uuid
from datetime import datetime, timezone
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# =============================================================
# Configurações de Ambiente
# Environment Settings
# =============================================================
DSM_ROOT = Path(
    os.environ.get("DSM_ROOT", Path(__file__).resolve().parents[1])
).resolve()
VERSION_FILE = DSM_ROOT / "version"


def read_dsm_version():
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
        return version or "unknown"
    except OSError:
        return "unknown"


DSM_VERSION = read_dsm_version()
DASHBOARD_DIR = DSM_ROOT / "dashboard"
WEB_DIR = DASHBOARD_DIR / "web"
API_DIR = DASHBOARD_DIR / "api"
WORKERS_DIR = DASHBOARD_DIR / "workers"
STATE_DIR = DASHBOARD_DIR / "state"
CONFIG_DIR = DASHBOARD_DIR / "config"
NOTIFICATION_DIR = DASHBOARD_DIR / "notifications"
LOG_DIR = DSM_ROOT / "logs"
OPERATIONS_DIR = DSM_ROOT / "runtime" / "operations"
CURRENT_OPERATION_FILE = OPERATIONS_DIR / "current.json"
INSTANCE_ROOT = (DSM_ROOT / "instances").resolve()
DATABASE_FILE = Path(
    os.environ.get("DSM_DATABASE", DSM_ROOT / "data" / "capivara.db")
).resolve()
DATABASE_DIR = DSM_ROOT / "database"

for module_dir in (
    DATABASE_DIR,
    DASHBOARD_DIR,
):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from users import hash_password, verify_password
import alerts as alert_store
from backend import DatabaseConfig
from backend_factory import create_backend
from dashboard_repository import DashboardRepository
from runtime_backend import backend_from_environment
from instance_network import (
    apply_instance_network,
    occupied_ports_for_agent,
)
from agent_ports_api import (
    agent_ports_for_user,
    list_agents_for_user,
    set_agent_ports_for_user,
)
from instance_placement import (
    resolve_instance_placement,
)
from infrastructure_http import dispatch_infrastructure_get
from agent_location_http import dispatch_agent_location_post

from region_preference_api import (
    region_options_for_user,
)

MAX_JSON_BODY = 12 * 1024 * 1024
MAX_INSTANCE_CONFIG = 1024 * 1024
MAX_INSTANCE_FILE = 8 * 1024 * 1024
MAX_INSTANCE_EDIT_FILE = 2 * 1024 * 1024

EDITABLE_INSTANCE_SUFFIXES = {
    ".txt",
    ".cfg",
    ".conf",
    ".config",
    ".ini",
    ".json",
    ".properties",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
    ".md",
    ".csv",
}

INSTANCE_CONFIG_SUFFIXES = {
    ".cfg",
    ".conf",
    ".config",
    ".ini",
    ".json",
    ".properties",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
}
PROTECTED_INSTANCE_PARTS = {".dsm", "runtime", "instance.conf"}
_PROVISION_LOCKS = defaultdict(threading.Lock)
INSTANCE_PERMISSIONS = {
    "viewer": {
        "instance.view",
        "logs.read",
        "game.files.read",
        "files.list",
        "files.download",
        "content.read",
        "backup.list",
    },
    "operator": {
        "instance.view",
        "instance.control",
        "instance.provision.retry",
        "logs.read",
        "game.files.read",
        "game.files.write",
        "files.list",
        "files.upload",
        "files.mkdir",
        "files.download",
        "content.read",
        "content.install",
        "content.remove",
        "content.verify",
        "backup.list",
        "backup.create",
    },
    "manager": {
        "instance.view",
        "instance.control",
        "instance.provision.retry",
        "instance.delete",
        "logs.read",
        "game.files.read",
        "game.files.write",
        "files.list",
        "files.upload",
        "files.mkdir",
        "files.download",
        "files.delete",
        "content.read",
        "content.install",
        "content.remove",
        "content.verify",
        "backup.list",
        "backup.create",
        "backup.restore",
        "backup.delete",
    },
}

NOTIFICATION_QUEUE = NOTIFICATION_DIR / "notification_queue.json"
NOTIFICATION_HISTORY = NOTIFICATION_DIR / "notification_history.log"
DISCORD_PENDING = NOTIFICATION_DIR / ".discord_pending"

HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("DASHBOARD_PORT", "8080"))
SERVER_NAME = f"DSM Dashboard v{DSM_VERSION}"
DEFAULT_CONTENT_TYPE = "application/octet-stream"

# =============================================================
# Dashboard State
# =============================================================
STATE_FILES = {
    "dashboard": STATE_DIR / "dashboard_state.json",
    "server": STATE_DIR / "server_state.json",
    "metrics": STATE_DIR / "metrics_state.json",
    "monitor": STATE_DIR / "monitor_state.json",
    "alerts": STATE_DIR / "alerts_state.json",
    "scheduler": STATE_DIR / "scheduler_state.json",
    "events": STATE_DIR / "events_state.json",
}

# =============================================================
# Rotas | Routes
# =============================================================
STATIC_FILES = {
    "/": WEB_DIR / "index.html",
    "/index.html": WEB_DIR / "index.html",
    "/login.html": WEB_DIR / "login.html",
    "/app.js": WEB_DIR / "app.js",
    "/auth.js": WEB_DIR / "auth.js",
    "/style.css": WEB_DIR / "style.css",
    "/installation-events.js": WEB_DIR / "installation-events.js",
    "/installation-events.css": WEB_DIR / "installation-events.css",
    "/catalog-v2.js": WEB_DIR / "catalog-v2.js",
    "/js/notifications.js": WEB_DIR / "js" / "notifications.js",
    "/js/dashboard-state.js": WEB_DIR / "js" / "dashboard-state.js",
    "/js/infrastructure-explorer.js": WEB_DIR / "js" / "infrastructure-explorer.js",
    "/js/infrastructure-shell.js": WEB_DIR / "js" / "infrastructure-shell.js",
    "/js/infrastructure-details.js": WEB_DIR / "js" / "infrastructure-details.js",
    "/css/infrastructure-explorer.css": WEB_DIR / "css" / "infrastructure-explorer.css",
    "/css/infrastructure-shell.css": WEB_DIR / "css" / "infrastructure-shell.css",
    "/css/infrastructure-details.css": WEB_DIR / "css" / "infrastructure-details.css",
    "/catalog-v2.css": WEB_DIR / "catalog-v2.css",
    "/css/alerts.css": WEB_DIR / "css" / "alerts.css",
    "/console.html": WEB_DIR / "console.html",
    "/console.js": WEB_DIR / "console.js",
    "/settings.html": WEB_DIR / "settings.html",
    "/users.html": WEB_DIR / "users.html",
    "/users.js": WEB_DIR / "users.js",
    "/agents.html": WEB_DIR / "agents.html",
    "/agents.js": WEB_DIR / "agents.js",
    "/agents.css": WEB_DIR / "agents.css",
    "/help.html": WEB_DIR / "help.html",
    "/help.css": WEB_DIR / "help.css",
    "/help.js": WEB_DIR / "help.js",
    "/customer.html": WEB_DIR / "customer.html",
    "/customer.js": WEB_DIR / "customer.js",
    "/customer.css": WEB_DIR / "customer.css",
    "/customer-delete.css": WEB_DIR / "customer-delete.css",
    "/customer-instance.html": WEB_DIR / "customer-instance.html",
    "/customer-instance.js": WEB_DIR / "customer-instance.js",
    "/contract-demo.html": WEB_DIR / "contract-demo.html",
    "/contract-demo.js": WEB_DIR / "contract-demo.js",
    "/runtime-selector.js": WEB_DIR / "runtime-selector.js",
    "/theme.js": WEB_DIR / "theme.js",
    "/components/header.html": WEB_DIR / "components/header.html",
    "/components/sidebar.html": WEB_DIR / "components/sidebar.html",
    "/components/cards.html": WEB_DIR / "components/cards.html",
    "/components/alerts.html": WEB_DIR / "components/alerts.html",
    "/favicon.ico": WEB_DIR / "favicon.ico",
}

API_ROUTES = {
    "server": "server.sh",
    "monitor": "monitor.sh",
    "metrics": "metrics.sh",
    "mods": "mods.sh",
    "backup": "backup.sh",
    "scheduler": "scheduler.sh",
    "alerts": "alerts.sh",
    "events": "events.sh",
    "discord": "discord.sh",
    "notifications": "notifications.sh",
    "console": "console.sh",
    "realtime": "realtime.sh",
    "health": "health.sh",
    "dsm": "dsm.sh",
    "runtime": "runtime.sh",
}


def catalog_instance_path(raw_path):
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("instance path is required")
    candidate = Path(raw_path).expanduser().resolve()
    try:
        candidate.relative_to(INSTANCE_ROOT)
    except ValueError as exc:
        raise ValueError("instance path must be inside DSM instances root") from exc
    if candidate == INSTANCE_ROOT:
        raise ValueError("instance path cannot be the instances root")
    return str(candidate)


def instance_metadata(instance_path):
    instance = Path(catalog_instance_path(str(instance_path)))
    metadata = read_json(instance / ".dsm" / "instance-metadata.json", {})
    if metadata:
        return metadata
    relative = instance.relative_to(INSTANCE_ROOT)
    if len(relative.parts) >= 3:
        return read_json(
            DSM_ROOT
            / "runtime"
            / "resources"
            / relative.parts[-3]
            / relative.parts[-2]
            / relative.parts[-1]
            / "instance.json",
            {},
        )
    return {}


def instance_customer_id(metadata):
    customer = metadata.get("customer", {}) if isinstance(metadata, dict) else {}
    return (
        customer.get("id")
        if isinstance(customer, dict)
        else metadata.get("customer_id")
    )


def can_access_instance(user, instance_path, write=False):
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    metadata = instance_metadata(instance_path)
    scope = user.get("scope_id", "")
    if user.get("role") == "controller":
        return bool(scope and scope == metadata.get("controller_id"))
    if user.get("role") == "customer":
        return bool(scope and scope == instance_customer_id(metadata))
    return not write and user.get("role") == "operator"


def game_files_root(instance_path):
    """
    Retorna exclusivamente a árvore de arquivos gerenciável
    pertencente à instância.

    Nunca aceita serverfiles/config como symbolic link.
    """

    instance = Path(catalog_instance_path(str(instance_path)))

    serverfiles = instance / "serverfiles"
    config = instance / "config"

    if serverfiles.is_symlink():
        raise ValueError("serverfiles cannot be a symbolic link")

    if serverfiles.is_dir():
        return serverfiles.resolve()

    if config.is_symlink():
        raise ValueError("config cannot be a symbolic link")

    if config.is_dir():
        return config.resolve()

    raise ValueError("instance game files directory not found")


def instance_config_path(
    instance_path,
    relative_path,
):
    if (
        not isinstance(relative_path, str)
        or not relative_path.strip()
    ):
        raise ValueError(
            "config file is required"
        )

    relative = Path(relative_path)

    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.suffix.lower()
        not in INSTANCE_CONFIG_SUFFIXES
    ):
        raise ValueError(
            "invalid instance config file"
        )

    candidate = instance_file_path(
        instance_path,
        relative_path,
        allow_missing=True,
    )

    return candidate


def list_instance_configs(instance_path):
    game_root = game_files_root(instance_path)
    if not game_root.exists():
        return []
    files = []
    for path in game_root.rglob("*"):
        if (
            path.is_file()
            and path.suffix.lower() in INSTANCE_CONFIG_SUFFIXES
            and not path.is_symlink()
        ):
            files.append(path.relative_to(game_root).as_posix())
    return sorted(files)


def database_connection(database_path=DATABASE_FILE):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def dashboard_repository(database_path=DATABASE_FILE):
    """Return persistence extracted from the dashboard server."""
    if (
        Path(database_path).resolve() == DATABASE_FILE
        and os.environ.get("DSM_DATABASE_DRIVER", "sqlite").strip().lower()
        not in {"", "sqlite", "sqlite3"}
    ):
        return DashboardRepository(backend_from_environment())
    return DashboardRepository(create_backend(DatabaseConfig(
        driver="sqlite",
        database=str(Path(database_path).expanduser().resolve()),
    )))


def customer_agents(user, database_path=DATABASE_FILE):
    if not user or user.get("role") != "customer" or not user.get("scope_id"):
        return []
    return dashboard_repository(database_path).customer_agents(user["scope_id"])


def customer_contracts(user, database_path=DATABASE_FILE):
    if not user or user.get("role") != "customer" or not user.get("scope_id"):
        return []
    rows = dashboard_repository(database_path).customer_contracts(user["scope_id"])
    now = datetime.now(timezone.utc)

    def contract_not_expired(ends_at):
        if not ends_at:
            return True
        if isinstance(ends_at, datetime):
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)
            return ends_at > now
        try:
            parsed = datetime.fromisoformat(
                str(ends_at).replace("Z", "+00:00")
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed > now
        except ValueError:
            return str(ends_at) > now.isoformat()
    return [
        row
        | {
            "available": row["status"] == "active"
            and contract_not_expired(row["ends_at"])
            and row["instances_used"] < row["instance_limit"]
        }
        for row in rows
    ]


def create_customer_instance(
    user,
    payload,
    root=DSM_ROOT,
    database_path=DATABASE_FILE,
):
    """Create a customer instance using extracted persistence."""
    if not user or user.get("role") != "customer" or not user.get("scope_id"):
        raise PermissionError("only a scoped customer can create an instance")
    game = str(payload.get("game", "")).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", game):
        raise ValueError("invalid game")
    runtime_id = str(payload.get("runtime_id", "")).strip()
    edition = str(payload.get("edition", "")).strip()
    version = str(payload.get("version", "")).strip()
    build = str(payload.get("build", "")).strip()
    for value, label in (
        (runtime_id, "runtime_id"), (edition, "edition"),
        (version, "version"), (build, "build"),
    ):
        if not value:
            raise ValueError(f"{label} is required")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", runtime_id):
        raise ValueError("invalid runtime_id")
    if not (root / "catalog" / "v2" / "runtimes" / game).is_dir():
        raise ValueError("game is not available in the catalog")
    try:
        runtime_def = _runtime_definition(root, game, runtime_id)
    except ValueError as exc:
        raise ValueError("requested runtime_id is not available for this game") from exc
    variant = runtime_def.get("variant") or runtime_def.get("loader") or runtime_def.get("edition")
    repository = dashboard_repository(database_path)

    placement = resolve_instance_placement(
        user,
        payload,
        repository,
    )

    contract_id = str(
        payload.get("contract_id", "")
    ).strip() or None

    plan = repository.create_customer_instance(
        customer_id=user["scope_id"],
        username=user["username"],
        game=game,
        runtime_id=runtime_id,
        edition=edition,
        variant=variant,
        version=version,
        build=build,
        instances_root=root / "instances",
        contract_id=contract_id,
        selected_agent_id=placement["agent_id"],
        network_profile=runtime_def.get("network"),
        occupied_ports_provider=occupied_ports_for_agent,
    )
    instance_path = plan["instance_path"]
    metadata_path = plan["metadata_path"]
    metadata = plan["metadata"]
    try:
        metadata_path.parent.mkdir(parents=True, exist_ok=False)
        (instance_path / "config").mkdir()
        (instance_path / "config" / "server.conf").write_text(
            f'# Configuração da instância {plan["name"]}\n'
            f'INSTANCE_ID="{plan["instance_id"]}"\nGAME_ID="{game}"\n',
            encoding="utf-8",
        )
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        resource = root / "runtime" / "resources" / plan["node_id"] / game / plan["instance_id"]
        resource.mkdir(parents=True, exist_ok=False)
        (resource / "instance.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (resource / "server.json").write_text(
            json.dumps({"status": {"state": "provisioning", "health": "pending"}}, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        repository.delete_instance(plan["instance_id"])
        if instance_path.exists():
            shutil.rmtree(instance_path)
        raise
    provision = start_instance_provisioning(
        root, database_path, plan["instance_id"], plan["node_id"], game,
        runtime_id, edition, version, build, instance_path, plan["agent_id"],
    )
    return {
        "created": True, "instance_id": plan["instance_id"], "name": plan["name"],
        "instance": str(instance_path), "agent_id": plan["agent_id"],
        "node_id": plan["node_id"],
        "game": game,
        "contract_id": plan["contract_id"],
        "placement": {
            "region_id": placement.get("region_id"),
            "datacenter_id": placement.get("datacenter_id"),
            "score": placement.get("score"),
            "reason": placement.get("reason"),
        },
        "provision": provision,
    }


def _provision_path(root, node_id, game, instance_id):
    return (
        root / "runtime" / "resources" / node_id / game / instance_id / "provision.json"
    )


def _set_provision(
    root,
    node_id,
    game,
    instance_id,
    *,
    database_path=DATABASE_FILE,
    status,
    stage,
    progress,
    message,
    **extra,
):
    payload = {
        "status": status,
        "stage": stage,
        "progress": progress,
        "message": message,
        "updated_at": int(time.time()),
        **extra,
    }
    write_json(
        _provision_path(root, node_id, game, instance_id),
        payload,
    )
    resource = _provision_path(root, node_id, game, instance_id).parent
    write_json(
        resource / "server.json",
        {
            "status": {
                "state": status,
                "health": (
                    "pending"
                    if status
                    in {
                        "queued",
                        "provisioning",
                        "pending_steam_auth",
                    }
                    else ("healthy" if status == "offline" else "error")
                ),
            }
        },
    )
    dashboard_repository(database_path).update_instance_status(
        instance_id,
        status,
    )
    return payload


def _instance_alert_context(
    database_path,
    instance_id,
):
    row = dashboard_repository(database_path).instance_context(
        instance_id
    )

    if row is None:
        raise ValueError(
            f"instance is not registered: {instance_id}"
        )

    return {
        "controller_id": row["controller_id"],
        "agent_id": row["agent_id"],
        "node_id": row["node_id"],
    }


def _open_provision_alert(
    database_path,
    *,
    instance_id,
    rule_id,
    level,
    message,
):
    alert_id = (
        f"{rule_id}:"
        f"{instance_id}"
    )

    try:
        context = _instance_alert_context(
            database_path,
            instance_id,
        )

        return alert_store.open_alert(
            Path(database_path),
            alert_id=alert_id,
            rule_id=rule_id,
            level=level,
            message=message,
            scope="instance",
            controller_id=context[
                "controller_id"
            ],
            agent_id=context[
                "agent_id"
            ],
            node_id=context[
                "node_id"
            ],
            instance_id=instance_id,
        )

    except Exception as exc:
        write_log(
            f"Falha ao persistir alerta "
            f"{alert_id}: {exc}"
        )

        return None


def _resolve_provision_alert(
    database_path,
    *,
    instance_id,
    rule_id,
):
    alert_id = (
        f"{rule_id}:"
        f"{instance_id}"
    )

    try:
        return alert_store.resolve_alert(
            Path(database_path),
            alert_id,
        )

    except Exception as exc:
        write_log(
            f"Falha ao resolver alerta "
            f"{alert_id}: {exc}"
        )

        return None


def _resolve_provision_alerts(
    database_path,
    instance_id,
):
    for rule_id in (
        "provision.runtime-missing",
        "provision.steam-auth-required",
        "provision.install-failed",
    ):
        _resolve_provision_alert(
            database_path,
            instance_id=instance_id,
            rule_id=rule_id,
        )


def _controller_alert(root, node_id, game, instance_id, agent_id, message):
    alert_id = f"steam-auth:{instance_id}"

    notification_center = root / "core" / "notification_center.sh"

    if not notification_center.is_file():
        write_log(
            f"Notification Center ausente para alerta {alert_id}: "
            f"{notification_center}"
        )
        return False

    try:
        result = subprocess.run(
            [
                "/bin/bash",
                str(notification_center),
                "create",
                alert_id,
                "CRITICAL",
                "Autenticação Steam necessária",
                message,
            ],
            env=os.environ | {"DSM_ROOT": str(root)},
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            write_log(
                f"Falha ao criar alerta {alert_id}: "
                f"{(result.stderr or result.stdout).strip()}"
            )
            return False

        return True

    except Exception as exc:
        write_log(f"Falha ao criar alerta {alert_id}: {exc}")
        return False


def _resolve_controller_alert(root, instance_id):
    alert_id = f"steam-auth:{instance_id}"

    notification_center = root / "core" / "notification_center.sh"

    if not notification_center.is_file():
        return False

    try:
        result = subprocess.run(
            [
                "/bin/bash",
                str(notification_center),
                "resolve",
                alert_id,
            ],
            env=os.environ | {"DSM_ROOT": str(root)},
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            write_log(
                f"Falha ao resolver alerta {alert_id}: "
                f"{(result.stderr or result.stdout).strip()}"
            )
            return False

        return True

    except Exception as exc:
        write_log(f"Falha ao resolver alerta {alert_id}: {exc}")
        return False


def _runtime_definition(root, game, runtime_id):
    definitions = (root / "catalog" / "v2" / "runtimes" / game).glob("*.json")

    for path in definitions:
        try:
            definition = read_json(path, {})
        except Exception:
            continue

        if definition.get("id") == runtime_id:
            return definition

    raise ValueError("runtime definition not found")


def _game_data_ready(game_data, definition):
    """
    Considera o game-data válido somente quando o diretório existe
    e contém o executável principal definido pelo runtime.

    Isso evita que um download anterior incompleto seja considerado
    uma instalação válida durante um retry.
    """

    if not game_data.is_dir():
        return False

    process = definition.get("process", {})

    executable = str(
        process.get("executable", "")
    ).strip()

    if not executable:
        return False

    executable_path = (
        game_data / executable
    ).resolve()

    try:
        executable_path.relative_to(
            game_data.resolve()
        )
    except ValueError:
        return False

    return executable_path.is_file()


def _game_data_directory(root, definition):
    configured = Path(definition.get("installation", {}).get("directory", ""))
    try:
        suffix = configured.relative_to("/opt/dsm/game-data")
    except ValueError:
        suffix = Path(definition.get("game", "unknown")) / str(
            definition.get("variant", "default")
        )
    return root / "game-data" / suffix


def _steam_user(root):
    configured = root / "config" / "providers" / "steam.conf"
    if configured.is_file():
        match = re.search(
            r"^\s*DSM_STEAM_USER\s*=\s*['\"]?([^'\"\s#]+)",
            configured.read_text(encoding="utf-8", errors="ignore"),
            re.M,
        )
        if match:
            return match.group(1)
    return os.environ.get("DSM_STEAM_USER", "")


def _provision_worker(
    root,
    database_path,
    instance_id,
    node_id,
    game,
    runtime_id,
    edition,
    version,
    build,
    instance_path,
    agent_id,
):
    try:
        definition = _runtime_definition(root, game, runtime_id)
    except (ValueError, OSError) as exc:
        _set_provision(
            root,
            node_id,
            game,
            instance_id,
            database_path=database_path,
            status="failed",
            stage="failed",
            progress=5,
            message="Não foi possível preparar o ambiente do jogo.",
        )
        _open_provision_alert(
            database_path,
            instance_id=instance_id,
            rule_id="provision.runtime-missing",
            level="CRITICAL",
            message=(
                f"Falha ao localizar o runtime "
                f"de {game}: {exc}"
            ),
        )
        _controller_alert(
            root,
            node_id,
            game,
            instance_id,
            agent_id,
            f"Falha ao localizar o runtime de {game}: {exc}",
        )
        return

    # persist a copy of the resolved runtime definition per-resource (best-effort)
    try:
        resource = (
            root
            / "runtime"
            / "resources"
            / node_id
            / game
            / instance_id
        )
        write_json(
            resource / "runtime.json",
            {
                "id": definition.get("id"),
                "game": definition.get("game"),
                "variant": definition.get("variant"),
                "edition": definition.get("edition"),
                "loader": definition.get("loader"),
                "loader_version": definition.get("loader_version"),
                "version": definition.get("version"),
            },
        )
    except Exception:
        # ignore write failures
        pass
        return
    game_data = _game_data_directory(root, definition)
    provider = definition.get("artifact", {}).get("provider", "")
    requires_steam = (
        provider == "steam"
        and definition.get("artifact", {}).get("auth", "anonymous") != "anonymous"
    )
    lock = _PROVISION_LOCKS[f"{root}:{game}"]
    with lock:
        if requires_steam and not _steam_user(root):
            message = (
                "A instalação está aguardando autenticação Steam pelo administrador."
            )
            _set_provision(
                root,
                node_id,
                game,
                instance_id,
                database_path=database_path,
                status="pending_steam_auth",
                stage="steam_auth",
                progress=15,
                message=message,
            )
            _open_provision_alert(
                database_path,
                instance_id=instance_id,
                rule_id="provision.steam-auth-required",
                level="CRITICAL",
                message=(
                    f"{game} / {instance_id}: "
                    f"Steam Guard, credencial ou licença "
                    f"exige autenticação no Agent {agent_id}."
                ),
            )
            _controller_alert(
                root,
                node_id,
                game,
                instance_id,
                agent_id,
                f"{game} / {instance_id}: Steam Guard, credencial ou licença exige autenticação no Agent {agent_id}.",
            )
            return
        _set_provision(
            root,
            node_id,
            game,
            instance_id,
            database_path=database_path,
            status="provisioning",
            stage="checking_game_data",
            progress=15,
            message="Verificando o jogo no game-data local do Agent…",
        )
        if not _game_data_ready(
               game_data,
               definition,
           ):
            _set_provision(
                root,
                node_id,
                game,
                instance_id,
                database_path=database_path,
                status="provisioning",
                stage="downloading",
                progress=35,
                message="Baixando e validando o jogo no game-data do Agent…",
            )
            env = os.environ | {
                "DSM_ROOT": str(root),
                "DSM_INSTANCE": instance_id,
            }
            if _steam_user(root):
                env["DSM_STEAM_USER"] = _steam_user(root)

            selector = version

            resolver = (
                definition
                .get("version", {})
                .get("resolver", "")
            )

            #
            # Paper suporta:
            #
            #   VERSION
            #   VERSION@BUILD
            #
            # Se o cliente escolheu uma build específica,
            # devemos respeitar essa escolha.
            #
            if resolver == "papermc" and build:
                selector = f"{version}@{build}"

            result = subprocess.run(
                [
                    "bash",
                    str(root / "installer" / "install_selection.sh"),
                    "install",
                    definition["id"],
                    selector,
                ],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=7200,
            )
            output = result.stdout or ""
            if result.returncode:
                if requires_steam and re.search(
                    r"steam|guard|auth|login", output, re.I
                ):
                    message = "A instalação está aguardando autenticação Steam pelo administrador."
                    _set_provision(
                        root,
                        node_id,
                        game,
                        instance_id,
                        database_path=database_path,
                        status="pending_steam_auth",
                        stage="steam_auth",
                        progress=35,
                        message=message,
                    )
                    _open_provision_alert(
                        database_path,
                        instance_id=instance_id,
                        rule_id="provision.steam-auth-required",
                        level="CRITICAL",
                        message=(
                            f"{game} / {instance_id}: "
                            f"autenticação Steam necessária "
                            f"no Agent {agent_id}."
                        ),
                    )
                    _controller_alert(
                        root,
                        node_id,
                        game,
                        instance_id,
                        agent_id,
                        f"{game} / {instance_id}: autenticação Steam necessária no Agent {agent_id}.",
                    )
                else:
                    _set_provision(
                        root,
                        node_id,
                        game,
                        instance_id,
                        database_path=database_path,
                        status="failed",
                        stage="failed",
                        progress=35,
                        message="Não foi possível instalar o jogo. O administrador foi notificado.",
                    )
                    _open_provision_alert(
                        database_path,
                        instance_id=instance_id,
                        rule_id="provision.install-failed",
                        level="CRITICAL",
                        message=(
                            f"Falha ao instalar {game} "
                            f"para {instance_id}: "
                            f"{output[-500:]}"
                        ),
                    )
                    _controller_alert(
                        root,
                        node_id,
                        game,
                        instance_id,
                        agent_id,
                        f"Falha ao instalar {game} para {instance_id}: {output[-500:]}",
                    )
                return
        _set_provision(
            root,
            node_id,
            game,
            instance_id,
            database_path=database_path,
            status="provisioning",
            stage="preparing_instance",
            progress=82,
            message="Preparando os arquivos exclusivos da instância…",
        )
        target = instance_path / "serverfiles"

        if not target.exists():
            try:
                shutil.copytree(
                    game_data,
                    target,
                    symlinks=False,
                    ignore=shutil.ignore_patterns(
                        ".dsm",
                        "runtime",
                    ),
                )
            except (OSError, shutil.Error) as exc:
                error_text = str(exc)

                no_space = (
                    getattr(exc, "errno", None) == 28
                    or "No space left on device"
                    in error_text
                )

                if no_space:
                    message = (
                        "Espaço insuficiente no Agent para "
                        "preparar os arquivos da instância."
                    )
                else:
                    message = (
                        "Não foi possível preparar os "
                        "arquivos da instância."
                    )

                _set_provision(
                    root,
                    node_id,
                    game,
                    instance_id,
                    database_path=database_path,
                    status="failed",
                    stage="failed",
                    progress=82,
                    message=message,
                    error=error_text,
                )

                write_log(
                    f"Falha ao preparar {game} / "
                    f"{instance_id}: {error_text}"
                )

                return

        process_definition = definition.get(
            "process",
            {},
        )

        executable = process_definition.get(
            "executable",
            "",
        )

        process_engine = str(
            process_definition.get(
                "engine",
                "native",
            )
            or "native"
        ).strip().lower()

        if not executable:
            _set_provision(
                root,
                node_id,
                game,
                instance_id,
                database_path=database_path,
                status="failed",
                stage="failed",
                progress=82,
                message=("O catálogo não definiu " "o executável do servidor."),
            )
            return

        executable_path = target / executable

        if not executable_path.is_file():
            _set_provision(
                root,
                node_id,
                game,
                instance_id,
                database_path=database_path,
                status="failed",
                stage="failed",
                progress=82,
                message=("Executável do servidor " "não encontrado."),
            )
            return

        if process_engine in {"native", "executable"}:
            if not os.access(
                executable_path,
                os.X_OK,
            ):
                executable_path.chmod(
                    executable_path.stat().st_mode | 0o111
                )

        working_dir = (
            process_definition.get(
                "working_dir",
                "",
            )
            or ""
        )

        args = (
            process_definition.get(
                "args",
                "",
            )
            or ""
        )

        if isinstance(args, list):
            args = " ".join(str(item) for item in args)

        reserved_ports = dashboard_repository(
            database_path
        ).instance_ports(
            instance_id
        )

        try:
            network_state = apply_instance_network(
                instance_path,
                definition,
                reserved_ports,
            )
        except (
            ValueError,
            RuntimeError,
            OSError,
        ) as exc:
            _set_provision(
                root,
                node_id,
                game,
                instance_id,
                database_path=database_path,
                status="failed",
                stage="failed",
                progress=82,
                message=(
                    "Não foi possível aplicar a "
                    "configuração de rede da instância."
                ),
                error=str(exc),
            )
            return

        network_args = network_state[
            "arguments"
        ]

        if network_args:
            rendered_network_args = " ".join(
                network_args
            )

            if args:
                args = (
                    f"{args} "
                    f"{rendered_network_args}"
                )
            else:
                args = (
                    rendered_network_args
                )

        network_env_lines = [
            f'{name}="{value}"'
            for name, value
            in sorted(
                network_state[
                    "environment"
                ].items()
            )
        ]

        def shell_value(value):
            return (
                str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
            )

        instance_conf = instance_path / "instance.conf"

        instance_conf.write_text(
            "\n".join(
                [
                    "# Capivara DSM",
                    "# Auto-generated instance runtime",
                    "",
                    f'INSTANCE_ID="{shell_value(instance_id)}"',
                    f'NODE_ID="{shell_value(node_id)}"',
                    "",
                    f'GAME="{shell_value(game)}"',
                    f'RUNTIME_ID="{shell_value(runtime_id)}"',
                    f'EDITION="{shell_value(edition)}"',
                    f'VARIANT="{shell_value(definition.get("variant") or definition.get("edition") or "")}"',
                    f'GAME_VERSION="{shell_value(version)}"',
                    f'BUILD_ID="{shell_value(build)}"',
                    "",
                    f'GAME_INSTALL="{shell_value(target)}"',
                    "",
                    f'PROCESS_ENGINE="{shell_value(process_engine)}"',
                    f'EXECUTABLE="{shell_value(executable)}"',
                    f'WORKING_DIR="{shell_value(working_dir)}"',
                    f'ARGS="{shell_value(args)}"',
                    *network_env_lines,
                    "",
                ]
            ),
            encoding="utf-8",
        )

        _set_provision(
            root,
            node_id,
            game,
            instance_id,
            database_path=database_path,
            status="offline",
            stage="completed",
            progress=100,
            message=("Instalação concluída. " "O servidor está pronto para iniciar."),
        )

        _resolve_provision_alerts(
            database_path,
            instance_id,
        )

        _resolve_controller_alert(
            root,
            instance_id,
        )


def start_instance_provisioning(
    root,
    database_path,
    instance_id,
    node_id,
    game,
    runtime_id,
    edition,
    version,
    build,
    instance_path,
    agent_id,
):
    payload = _set_provision(
        root,
        node_id,
        game,
        instance_id,
        database_path=database_path,
        status="queued",
        stage="queued",
        progress=5,
        message="Instalação aguardando o Agent…",
    )
    thread = threading.Thread(
        target=_provision_worker,
        args=(
            root,
            database_path,
            instance_id,
            node_id,
            game,
            runtime_id,
            edition,
            version,
            build,
            instance_path,
            agent_id,
        ),
        daemon=True,
        name=f"provision-{instance_id}",
    )
    thread.start()
    return payload


def retry_instance_provisioning(
    user,
    instance_path,
    database_path=DATABASE_FILE,
):
    instance = Path(
        catalog_instance_path(
            str(instance_path)
        )
    )

    relative = instance.relative_to(
        INSTANCE_ROOT
    )

    if len(relative.parts) != 3:
        raise ValueError(
            "instance path must identify server, game and instance"
        )

    node_id, game, instance_id = (
        relative.parts
    )

    with closing(
        database_connection(
            database_path
        )
    ) as connection:

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        row = connection.execute(
            """
            SELECT
                id,
                node_id,
                game_id,
                agent_id,
                runtime_id,
                edition,
                game_version,
                build_id,
                status
            FROM instances
            WHERE id=?
            """,
            (instance_id,),
        ).fetchone()

        if not row:
            connection.rollback()

            raise ValueError(
                "instance is not registered"
            )

        if (
            row["node_id"] != node_id
            or row["game_id"] != game
        ):
            connection.rollback()

            raise ValueError(
                "instance identity does not match database"
            )

        if row["status"] not in {
            "failed",
            "pending_steam_auth",
        }:
            connection.rollback()

            raise ValueError(
                "only a failed or pending Steam authentication "
                "provision can be retried"
            )

        runtime_id = str(
            row["runtime_id"] or ""
        ).strip()

        edition = str(
            row["edition"] or ""
        ).strip()

        version = str(
            row["game_version"] or ""
        ).strip()

        build = str(
            row["build_id"] or ""
        ).strip()

        agent_id = str(
            row["agent_id"] or ""
        ).strip()

        if not all(
            (
                runtime_id,
                edition,
                version,
                build,
                agent_id,
            )
        ):
            connection.rollback()

            raise ValueError(
                "instance runtime selection is incomplete"
            )

        #
        # Reserva o retry antes de liberar a transação.
        # Um segundo clique simultâneo encontrará status queued
        # e não iniciará outra thread.
        #
        connection.execute(
            """
            UPDATE instances
            SET
                status='queued',
                updated_at=strftime(
                    '%Y-%m-%dT%H:%M:%fZ',
                    'now'
                )
            WHERE id=?
              AND status IN ('failed', 'pending_steam_auth')
            """,
            (instance_id,),
        )

        connection.commit()

    audit(
        user,
        "instance.provision.retry",
        "started",
        instance_id,
        (
            f"runtime={runtime_id};"
            f"version={version};"
            f"build={build}"
        ),
        database_path=database_path,
    )

    provision = start_instance_provisioning(
        DSM_ROOT,
        database_path,
        instance_id,
        node_id,
        game,
        runtime_id,
        edition,
        version,
        build,
        instance,
        agent_id,
    )

    return {
        "retried": True,
        "instance_id": instance_id,
        "runtime_id": runtime_id,
        "edition": edition,
        "version": version,
        "build": build,
        "provision": provision,
    }


def retry_instance_provisioning(
    user,
    instance_path,
    database_path=DATABASE_FILE,
):
    """Reserve and restart provisioning through DashboardRepository."""
    instance = Path(catalog_instance_path(str(instance_path)))
    relative = instance.relative_to(INSTANCE_ROOT)
    if len(relative.parts) != 3:
        raise ValueError("instance path must identify server, game and instance")
    node_id, game, instance_id = relative.parts
    row = dashboard_repository(database_path).reserve_retry(
        instance_id,
        node_id,
        game,
    )
    runtime_id = str(row["runtime_id"] or "").strip()
    edition = str(row["edition"] or "").strip()
    version = str(row["game_version"] or "").strip()
    build = str(row["build_id"] or "").strip()
    agent_id = str(row["agent_id"] or "").strip()
    if not all((runtime_id, edition, version, build, agent_id)):
        dashboard_repository(database_path).update_instance_status(
            instance_id,
            row["status"],
        )
        raise ValueError("instance runtime selection is incomplete")
    audit(
        user, "instance.provision.retry", "started", instance_id,
        f"runtime={runtime_id};version={version};build={build}",
        database_path=database_path,
    )
    provision = start_instance_provisioning(
        DSM_ROOT, database_path, instance_id, node_id, game,
        runtime_id, edition, version, build, instance, agent_id,
    )
    return {
        "retried": True, "instance_id": instance_id,
        "runtime_id": runtime_id, "edition": edition,
        "version": version, "build": build, "provision": provision,
    }


def instance_identity_path(server, game, instance):
    for value in (server, game, instance):
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value
        ):
            raise ValueError("invalid instance identity")
    return catalog_instance_path(str(INSTANCE_ROOT / server / game / instance))


def instance_permission_profile(user, instance_path, database_path=DATABASE_FILE):
    if not user:
        return None
    if user.get("role") == "admin":
        return "manager"
    metadata = instance_metadata(instance_path)
    if user.get("role") == "customer" and user.get("scope_id") == instance_customer_id(
        metadata
    ):
        return "manager"
    if user.get("role") == "controller" and user.get("scope_id") == metadata.get(
        "controller_id"
    ):
        return "operator"
    try:
        return dashboard_repository(database_path).permission_profile(
            user.get("username"),
            Path(instance_path).name,
        )
    except Exception:
        return None


def has_instance_permission(
    user, instance_path, permission, database_path=DATABASE_FILE
):
    profile = instance_permission_profile(user, instance_path, database_path)
    return bool(profile and permission in INSTANCE_PERMISSIONS[profile])


def audit(
    user, action, result, instance_id=None, details=None, database_path=DATABASE_FILE
):
    try:
        dashboard_repository(database_path).write_audit(
            user.get("username", "system") if user else "system",
            instance_id,
            action,
            result,
            details,
        )
    except Exception:
        pass


def instance_file_path(
    instance_path,
    relative_path,
    *,
    allow_missing=False,
):
    game_root = game_files_root(
        instance_path,
    ).resolve()

    relative = Path(
        str(relative_path or "."),
    )

    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid instance file path")

    meaningful = [part for part in relative.parts if part not in {"", "."}]

    if meaningful and meaningful[0] in PROTECTED_INSTANCE_PARTS:
        raise ValueError("protected instance path")

    # ---------------------------------------------------------
    # Não permite symlinks em nenhum componente do caminho
    # ---------------------------------------------------------
    current = game_root

    for part in meaningful:
        current = current / part

        if current.is_symlink():
            raise ValueError("symbolic links are not allowed")

    candidate = (game_root / relative).resolve(
        strict=False,
    )

    try:
        candidate.relative_to(
            game_root,
        )
    except ValueError as exc:
        raise ValueError("file must be inside the instance") from exc

    if not allow_missing and not candidate.exists():
        raise ValueError("instance file not found")

    return candidate


def instance_text_file(
    instance_path,
    relative_path,
):
    path = instance_file_path(
        instance_path,
        relative_path,
    )

    if not path.is_file():
        raise ValueError("path is not a file")

    if path.suffix.lower() not in EDITABLE_INSTANCE_SUFFIXES:
        raise ValueError("file type is not editable")

    if path.stat().st_size > MAX_INSTANCE_EDIT_FILE:
        raise ValueError("file is too large to edit")

    return path


def read_instance_text_file(
    instance_path,
    relative_path,
):
    path = instance_text_file(
        instance_path,
        relative_path,
    )

    try:
        content = path.read_text(
            encoding="utf-8",
        )
    except UnicodeDecodeError as exc:
        raise ValueError("file is not valid UTF-8 text") from exc

    return {
        "path": str(relative_path),
        "content": content,
        "size": path.stat().st_size,
    }


def write_instance_text_file(
    instance_path,
    relative_path,
    content,
):
    path = instance_text_file(
        instance_path,
        relative_path,
    )

    if not isinstance(content, str):
        raise ValueError("content must be text")

    encoded = content.encode("utf-8")

    if len(encoded) > MAX_INSTANCE_EDIT_FILE:
        raise ValueError("file content is too large")

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")

    try:
        temporary.write_bytes(encoded)
        os.replace(
            temporary,
            path,
        )
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "saved": True,
        "path": str(relative_path),
        "size": len(encoded),
    }


def list_instance_files(
    instance_path,
    relative_path=".",
):
    directory = instance_file_path(
        instance_path,
        relative_path,
    )

    if not directory.is_dir():
        raise ValueError("instance path is not a directory")

    entries = []

    for child in sorted(
        directory.iterdir(),
        key=lambda item: (
            not item.is_dir(),
            item.name.lower(),
        ),
    ):
        if child.name in PROTECTED_INSTANCE_PARTS or child.is_symlink():
            continue

        stat = child.stat()

        entries.append(
            {
                "name": child.name,
                "directory": child.is_dir(),
                "size": (stat.st_size if child.is_file() else None),
                "modified_at": int(stat.st_mtime),
                "editable": (
                    child.is_file()
                    and child.suffix.lower() in EDITABLE_INSTANCE_SUFFIXES
                    and stat.st_size <= MAX_INSTANCE_EDIT_FILE
                ),
            }
        )

    return entries


def search_instance_files(
    instance_path,
    search_term,
    limit=200,
):
    game_root = game_files_root(
        instance_path,
    ).resolve()

    term = str(
        search_term or ""
    ).strip().lower()

    if not term:
        return []

    limit = max(
        1,
        min(
            int(limit),
            500,
        ),
    )

    results = []

    for path in game_root.rglob("*"):

        # Nunca segue ou exibe links simbólicos.
        if path.is_symlink():
            continue

        try:
            relative = path.relative_to(
                game_root,
            )
        except ValueError:
            continue

        # Evita qualquer componente protegido.
        if any(
            part in PROTECTED_INSTANCE_PARTS
            for part in relative.parts
        ):
            continue

        relative_text = relative.as_posix()

        if (
            term not in path.name.lower()
            and term not in relative_text.lower()
        ):
            continue

        try:
            stat = path.stat()
        except OSError:
            continue

        results.append(
            {
                "name": path.name,
                "path": relative_text,
                "directory": path.is_dir(),
                "size": (
                    stat.st_size
                    if path.is_file()
                    else None
                ),
                "modified_at": int(
                    stat.st_mtime
                ),
                "editable": (
                    path.is_file()
                    and path.suffix.lower()
                    in EDITABLE_INSTANCE_SUFFIXES
                    and stat.st_size
                    <= MAX_INSTANCE_EDIT_FILE
                ),
            }
        )

        if len(results) >= limit:
            break

    return results


def create_instance_directory(
    instance_path,
    relative_path,
    name,
):
    if not isinstance(name, str):
        raise ValueError("directory name must be text")

    name = name.strip()

    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or Path(name).name != name
        or name in PROTECTED_INSTANCE_PARTS
    ):
        raise ValueError("invalid directory name")

    parent = instance_file_path(
        instance_path,
        relative_path or ".",
    )

    if not parent.is_dir():
        raise ValueError(
            "directory destination is not a directory"
        )

    destination = instance_file_path(
        instance_path,
        str(
            Path(relative_path or ".")
            / name
        ),
        allow_missing=True,
    )

    if destination.exists():
        raise ValueError(
            "a file or directory with this name already exists"
        )

    destination.mkdir(
        mode=0o750,
        parents=False,
        exist_ok=False,
    )

    return {
        "created": True,
        "name": name,
        "path": str(
            destination.relative_to(
                game_files_root(instance_path)
            )
        ),
    }


def instance_logs(instance_path, limit=200):
    instance = Path(catalog_instance_path(str(instance_path)))
    candidates = [
        instance / "runtime" / "instance.log",
        instance / "logs" / "server.log",
    ]
    candidates.extend(
        sorted(
            (instance / "logs").glob("*.log"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if (instance / "logs").is_dir()
        else []
    )
    logfile = next((path for path in candidates if path.is_file()), None)
    if not logfile:
        return {"file": None, "logs": []}
    with logfile.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return {
        "file": logfile.name,
        "logs": [line.rstrip() for line in lines[-max(1, min(limit, 1000)) :]],
    }


def instance_backup_directory(instance_path):
    return DSM_ROOT / "backups" / "instances" / Path(instance_path).name


def list_instance_backups(instance_path):
    directory = instance_backup_directory(instance_path)
    if not directory.is_dir():
        return []
    return [
        {
            "name": path.name,
            "size": path.stat().st_size,
            "created_at": int(path.stat().st_mtime),
        }
        for path in sorted(
            directory.glob("*.tar.gz"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    ]


def create_instance_backup(instance_path):
    instance = Path(catalog_instance_path(str(instance_path)))
    directory = instance_backup_directory(instance)
    directory.mkdir(parents=True, exist_ok=True)
    name = f"manual-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.tar.gz"
    destination = directory / name
    temporary = destination.with_suffix(destination.suffix + ".part")
    with tarfile.open(temporary, "w:gz") as archive:
        archive.add(
            instance,
            arcname=instance.name,
            recursive=True,
            filter=lambda member: None if member.issym() or member.islnk() else member,
        )
    os.replace(temporary, destination)
    return {"name": destination.name, "size": destination.stat().st_size}


def instance_backup_path(instance_path, name):
    if not isinstance(name, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz", name
    ):
        raise ValueError("invalid backup name")
    path = (instance_backup_directory(instance_path) / name).resolve()
    try:
        path.relative_to(instance_backup_directory(instance_path).resolve())
    except ValueError as exc:
        raise ValueError("invalid backup path") from exc
    if not path.is_file():
        raise ValueError("backup not found")
    return path


def restore_instance_backup(user, instance_path, name):
    instance = Path(catalog_instance_path(str(instance_path)))
    backup = instance_backup_path(instance, name)
    control_instance(user, instance, "stop")
    with tempfile.TemporaryDirectory(
        prefix="dsm-restore-", dir=instance.parent
    ) as temporary_name:
        temporary = Path(temporary_name)
        with tarfile.open(backup, "r:gz") as archive:
            for member in archive.getmembers():
                member_path = Path(member.name)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or not member_path.parts
                    or member_path.parts[0] != instance.name
                ):
                    raise ValueError("backup contains an invalid path")
                if not (member.isfile() or member.isdir()):
                    raise ValueError("backup contains an unsupported entry")
            archive.extractall(temporary)
        restored = temporary / instance.name
        if not restored.is_dir():
            raise ValueError("backup does not contain the instance directory")
        previous = instance.with_name(
            f".{instance.name}.restore-{uuid.uuid4().hex[:8]}"
        )
        instance.rename(previous)
        try:
            restored.rename(instance)
            shutil.rmtree(previous)
        except Exception:
            if not instance.exists() and previous.exists():
                previous.rename(instance)
            raise
    audit(user, "backup.restore", "success", instance.name, name)
    return {"restored": True, "name": name}


def control_instance(
    user,
    instance_path,
    action,
    database_path=DATABASE_FILE,
):
    if action not in {
        "start",
        "stop",
        "restart",
    }:
        raise ValueError("invalid instance action")

    instance = Path(
        catalog_instance_path(
            str(instance_path),
        )
    )

    relative = instance.relative_to(INSTANCE_ROOT)

    if len(relative.parts) != 3:
        raise ValueError("instance path must identify " "server, game and instance")

    node_id, game, instance_id = relative.parts

    success, result = run_api_script(
        "instance.sh",
        action,
        str(instance),
        user=user,
    )

    if success:
        resource = (
            DSM_ROOT
            / "runtime"
            / "resources"
            / node_id
            / game
            / instance_id
        )

        #
        # O instance.sh publica o estado observado através
        # de process_running(). Esse estado é a fonte de
        # verdade após a operação.
        #
        server_state = read_json(
            resource / "server.json",
            {},
        )

        status = server_state.get(
            "status",
            {},
        )

        state = status.get(
            "state",
            "offline",
        )

        if state not in {
            "online",
            "offline",
        }:
            state = "offline"

        dashboard_repository(database_path).update_instance_status(
            instance_id,
            state,
        )

    audit(
        user,
        f"instance.{action}",
        ("success" if success else "error"),
        instance_id,
        (result.get("error") if isinstance(result, dict) else None),
        database_path=database_path,
    )

    return success, result


def delete_instance(
    user, instance_path, final_backup=False, database_path=DATABASE_FILE
):
    instance = Path(catalog_instance_path(str(instance_path)))
    instance_id = instance.name
    # A partial deletion may have removed the local game directory already. The
    # SQLite record remains authoritative, so a retry must finish its cleanup
    # instead of returning the operating system's raw ENOENT error.
    instance_exists = instance.is_dir()
    if final_backup and instance_exists:
        create_instance_backup(instance)
    if instance_exists:
        control_instance(user, instance, "stop")
    relative = instance.relative_to(INSTANCE_ROOT)
    if len(relative.parts) != 3:
        raise ValueError("instance path must identify server, game and instance")
    server_id, game_id, _ = relative.parts
    resource = DSM_ROOT / "runtime" / "resources" / server_id / game_id / instance_id
    quarantine = instance.with_name(f".{instance.name}.deleting-{uuid.uuid4().hex[:8]}")
    if instance_exists:
        instance.rename(quarantine)
    try:
        deleted = dashboard_repository(database_path).delete_instance(
            instance_id
        )
        if not deleted:
            raise ValueError("instance is not registered or was already deleted")
        if quarantine.exists():
            shutil.rmtree(quarantine)
        if resource.is_dir():
            shutil.rmtree(resource)
    except Exception:
        if instance_exists and quarantine.exists() and not instance.exists():
            quarantine.rename(instance)
        audit(user, "instance.delete", "error", instance_id)
        raise
    audit(user, "instance.delete", "success", instance_id)
    return {
        "deleted": True,
        "instance_id": instance_id,
        "directory_was_missing": not instance_exists,
    }


def catalog_api(action, *args, user=None):
    timeout = 7200 if action == "environment-install" else 300
    success, data = run_api_script(
        "catalog.sh", action, *args, user=user, timeout=timeout
    )
    return success, data


POST_ROUTES = {
    "/api/server/start": "start",
    "/api/server/stop": "stop",
    "/api/server/restart": "restart",
}


def valid_instance_metadata(metadata):
    if not isinstance(metadata, dict):
        return False
    customer = metadata.get("customer")
    customer_id = (
        customer.get("id")
        if isinstance(customer, dict)
        else metadata.get("customer_id")
    )
    return all(
        isinstance(value, str) and bool(value.strip())
        for value in (
            metadata.get("controller_id"),
            metadata.get("agent_id"),
            customer_id,
        )
    )


def api_runtime_summary(server, game, instance):
    base = (
        DSM_ROOT
        / "runtime"
        / "resources"
        / server
        / game
        / instance
    )

    if not base.exists():
        return {
            "error": "runtime resource not found",
            "server": server,
            "game": game,
            "instance": instance,
        }

    instance_metadata = read_json(
        base / "instance.json",
        {},
    )

    if not valid_instance_metadata(
        instance_metadata
    ):
        return {
            "error": "instance ownership metadata is incomplete",
            "server": server,
            "game": game,
            "instance": instance,
        }

    instance_path = (
        INSTANCE_ROOT
        / server
        / game
        / instance
    )

    # ---------------------------------------------------------
    # Estado real da instância
    #
    # server.json é apenas estado persistido e pode ficar
    # obsoleto. O processo real tem prioridade.
    # ---------------------------------------------------------

    server_state = read_json(
        base / "server.json",
        {},
    )

    live_pid = None

    pid_file = (
        instance_path
        / "runtime"
        / "process.pid"
    )

    if pid_file.is_file():
        try:
            pid = int(
                pid_file.read_text(
                    encoding="utf-8",
                    errors="ignore",
                ).strip()
            )

            proc_path = Path(
                f"/proc/{pid}"
            )

            cmdline_path = (
                proc_path
                / "cmdline"
            )

            if (
                pid > 0
                and proc_path.is_dir()
                and cmdline_path.is_file()
            ):
                cmdline = (
                    cmdline_path
                    .read_bytes()
                    .replace(
                        b"\\x00",
                        b" ",
                    )
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )

                if (
                    str(instance_path)
                    in cmdline
                ):
                    live_pid = pid

        except (
            ValueError,
            OSError,
        ):
            live_pid = None

    server_state["status"] = {
        "state": (
            "online"
            if live_pid is not None
            else "offline"
        ),
        "health": (
            "healthy"
            if live_pid is not None
            else "offline"
        ),
    }

    server_state["pid"] = live_pid

    server_state["identity"] = {
        "server": server,
        "game": game,
        "instance": instance,
    }

    #
    # Reconciliação do estado persistido.
    #
    # O processo observado acima é a fonte de verdade.
    # server.json e instances.status são projeções desse
    # estado e podem ter ficado obsoletos após uma queda
    # espontânea do processo.
    #
    observed_state = (
        "online"
        if live_pid is not None
        else "offline"
    )

    write_json(
        base / "server.json",
        server_state,
    )

    try:
        dashboard_repository(DATABASE_FILE).reconcile_instance_status(
            instance,
            observed_state,
        )
    except Exception:
        #
        # A leitura do runtime deve continuar disponível
        # mesmo se a persistência do estado falhar.
        #
        pass

    mods = read_json(
        base / "mods.json",
        {},
    )

    if not isinstance(
        mods,
        dict,
    ):
        mods = {}

    mods.setdefault(
        "server",
        server,
    )

    mods.setdefault(
        "instance",
        instance,
    )

    metrics = read_json(
        base / "metrics.json",
        {},
    )

    events = read_json(
        base / "events.json",
        [],
    )

    # ---------------------------------------------------------
    # Backup mais recente
    # ---------------------------------------------------------

    backup = read_json(
        base / "backup.json",
        {},
    )

    if not isinstance(
        backup,
        dict,
    ):
        backup = {}

    backup_dir = (
        DSM_ROOT
        / "backups"
        / "instances"
        / instance
    )

    try:
        if backup_dir.is_dir():
            candidates = [
                item
                for item
                in backup_dir.iterdir()
                if (
                    item.is_file()
                    and not item.name.endswith(
                        ".part"
                    )
                )
            ]

            if candidates:
                latest = max(
                    candidates,
                    key=lambda item:
                        item.stat().st_mtime,
                )

                latest_stat = (
                    latest.stat()
                )

                backup.update({
                    "last_backup":
                        latest.name,
                    "created_at":
                        int(
                            latest_stat.st_mtime
                        ),
                    "size":
                        latest_stat.st_size,
                })

    except OSError:
        pass

    runtime_definition = read_json(
        base / "runtime.json",
        {},
    )

    return {
        "server": server,
        "game": game,
        "instance": instance,
        "server_state": server_state,
        "mods": mods,
        "metrics": metrics,
        "events": events,
        "backup": backup,
        "instance_metadata":
            instance_metadata,
        "provision": read_json(
            base / "provision.json",
            {},
        ),
        "runtime_definition":
            runtime_definition,
    }


def reinstall_instance_from_game_data(
    user,
    server,
    game,
    instance,
    preserve_config=True,
):
    """
    Recria os serverfiles de uma instância usando a instalação
    previamente validada no game-data do Agent.

    Não baixa novamente o jogo.
    """

    instance_path = Path(
        instance_identity_path(
            server,
            game,
            instance,
        )
    )

    if not can_access_instance(
        user,
        instance_path,
        write=True,
    ):
        raise PermissionError(
            "Usuário sem permissão para reinstalar esta instância."
        )

    metadata = instance_metadata(
        instance_path
    )

    runtime = (
        metadata.get("runtime", {})
        if isinstance(metadata, dict)
        else {}
    )

    runtime_id = (
        runtime.get("id")
        or metadata.get("runtime_id")
        or ""
    )

    if not runtime_id:
        raise ValueError(
            "A instância não possui Runtime definido."
        )

    definition = _runtime_definition(
        DSM_ROOT,
        game,
        runtime_id,
    )

    if not definition:
        raise ValueError(
            f"Runtime não encontrado: {runtime_id}"
        )

    game_data = _game_data_directory(
        DSM_ROOT,
        definition,
    )

    if not game_data.is_dir():
        raise ValueError(
            "O jogo não está instalado no game-data do Agent."
        )

    process_definition = (
        definition.get("process", {})
        if isinstance(definition, dict)
        else {}
    )

    executable = str(
        process_definition.get(
            "executable",
            "",
        )
        or ""
    )

    if not executable:
        raise ValueError(
            "Runtime não define executável."
        )

    source_executable = (
        game_data / executable
    )

    if not source_executable.is_file():
        raise ValueError(
            "A instalação do game-data está incompleta: "
            f"{source_executable}"
        )

    target = (
        instance_path / "serverfiles"
    )

    runtime_dir = (
        instance_path / "runtime"
    )

    runtime_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    pid_file = (
        runtime_dir / "process.pid"
    )

    #
    # Não permitir reinstalação com processo ativo.
    #
    if pid_file.is_file():
        try:
            pid = int(
                pid_file.read_text(
                    encoding="utf-8"
                ).strip()
            )

            if (
                pid > 0
                and Path(
                    f"/proc/{pid}"
                ).exists()
            ):
                raise ValueError(
                    "A instância está online. "
                    "Pare o servidor antes da reinstalação."
                )
        except ValueError as exc:
            if "online" in str(exc):
                raise

    timestamp = time.strftime(
        "%Y%m%d-%H%M%S"
    )

    staging = (
        instance_path
        / f"serverfiles.reinstall-{timestamp}"
    )

    previous = (
        instance_path
        / f"serverfiles.previous-{timestamp}"
    )

    if staging.exists():
        shutil.rmtree(staging)

    #
    # Copia primeiro para staging.
    #
    shutil.copytree(
        game_data,
        staging,
        symlinks=False,
        ignore=shutil.ignore_patterns(
            ".dsm",
            "runtime",
        ),
    )

    staged_executable = (
        staging / executable
    )

    if not staged_executable.is_file():
        shutil.rmtree(
            staging,
            ignore_errors=True,
        )
        raise ValueError(
            "Reinstalação inválida: "
            "executável não foi copiado."
        )

    #
    # Preservar arquivos específicos da instância.
    #
    preserved = []

    if preserve_config and target.is_dir():
        #
        # Dados persistentes da instância.
        #
        # Reinstalação do runtime não deve apagar mundo,
        # plugins ou configurações do cliente.
        #
        preserve_names = (
            "server.properties",
            "eula.txt",
            "whitelist.json",
            "ops.json",
            "banned-ips.json",
            "banned-players.json",
            "bukkit.yml",
            "spigot.yml",
            "commands.yml",
            "permissions.yml",
            "help.yml",
            "world",
            "world_nether",
            "world_the_end",
            "plugins",
            "config",
        )

        for name in preserve_names:
            source = target / name

            if not source.exists():
                continue

            destination = staging / name

            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()

            if source.is_dir():
                shutil.copytree(
                    source,
                    destination,
                    symlinks=False,
                )
            elif source.is_file():
                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                shutil.copy2(
                    source,
                    destination,
                )
            else:
                continue

            preserved.append(name)

    #
    # Troca atômica.
    #
    try:
        if target.exists():
            target.rename(previous)

        staging.rename(target)

    except Exception:
        if target.exists():
            shutil.rmtree(
                target,
                ignore_errors=True,
            )

        if previous.exists():
            previous.rename(target)

        shutil.rmtree(
            staging,
            ignore_errors=True,
        )

        raise

    #
    # Após ativação bem-sucedida, removemos a instalação anterior.
    #
    if previous.exists():
        shutil.rmtree(
            previous,
            ignore_errors=True,
        )

    audit(
        user,
        "instance.reinstall",
        "success",
        instance,
        details=json.dumps(
            {
                "runtime_id": runtime_id,
                "game_data": str(game_data),
                "preserved": preserved,
            },
            ensure_ascii=False,
        ),
    )

    return {
        "success": True,
        "instance": instance,
        "runtime_id": runtime_id,
        "source": str(game_data),
        "destination": str(target),
        "preserved": preserved,
        "message": (
            "Instância reinstalada a partir "
            "do game-data do Agent."
        ),
    }


def api_runtime_list(database_path=DATABASE_FILE):
    root = DSM_ROOT / "runtime" / "resources"
    resources = []

    if not root.exists():
        return []

    try:
        registered = dashboard_repository(
            database_path
        ).registered_instances()
    except Exception:
        registered = None

    for server_dir in root.iterdir():
        if not server_dir.is_dir():
            continue

        for game_dir in server_dir.iterdir():
            if not game_dir.is_dir():
                continue

            for instance_dir in game_dir.iterdir():
                if not instance_dir.is_dir():
                    continue
                identity = (server_dir.name, game_dir.name, instance_dir.name)
                if registered is not None and identity not in registered:
                    continue

                server_state = read_json(instance_dir / "server.json", {})
                instance_metadata = read_json(instance_dir / "instance.json", {})
                if not valid_instance_metadata(instance_metadata):
                    continue

                raw_status = server_state.get("status", {})
                status = (
                    raw_status.get("state", "unknown")
                    if isinstance(raw_status, dict)
                    else raw_status
                )
                health = (
                    raw_status.get("health", server_state.get("health", "unknown"))
                    if isinstance(raw_status, dict)
                    else server_state.get("health", "unknown")
                )

                resources.append(
                    {
                        "server": server_dir.name,
                        "game": game_dir.name,
                        "instance": instance_dir.name,
                        "status": status,
                        "health": health,
                    }
                )

    return resources


# =============================================================
# Funções Auxiliares | Auxiliary Functions
# =============================================================
def read_json(path: Path, default=None):
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return default


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=4, ensure_ascii=False)


def write_log(message):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logfile = LOG_DIR / "dashboard.log"
        with logfile.open("a", encoding="utf-8") as fp:
            fp.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        # Logging must not turn a recoverable persistence error into
        # a dashboard request failure (for example on read-only media).
        return None


# =============================================================
# Lógica de Usuários e Segurança
# User and Security Logic
# =============================================================
_USERS_LOCK = threading.Lock()


def load_users(database_path=DATABASE_FILE):
    """Load dashboard identities through DashboardRepository."""
    try:
        rows = dashboard_repository(database_path).load_users()
    except Exception:
        return {}
    return {
        row["username"]: {
            "password_hash": row["password_hash"],
            "role": row["role"],
            "scope_id": row["scope_id"] or "",
            "active": bool(row["active"]),
        }
        for row in rows
    }


def authenticate(headers):
    auth = headers.get("Authorization")
    if not auth or not auth.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
        username = username.strip().lower()
        users = load_users()
        if username in users:
            user = users[username]
            if user.get("active", True) and verify_password(
                password, user["password_hash"]
            ):
                return {
                    "username": username,
                    "role": user["role"],
                    "scope_id": user.get("scope_id", ""),
                }
    except Exception:
        pass
    return None


READ_ROLES = {"admin", "operator", "controller", "customer"}
WRITE_ROLES = {"admin", "operator", "controller", "customer"}


def can_read(user):
    return user is not None and user["role"] in READ_ROLES


def can_write(user):
    return user is not None and user["role"] in WRITE_ROLES


def public_users():
    return [
        {
            "username": username,
            "role": data["role"],
            "scope_id": data.get("scope_id", ""),
            "active": data.get("active", True),
        }
        for username, data in sorted(load_users().items())
    ]


def user_scope_options(database_path=DATABASE_FILE):
    return dashboard_repository(database_path).scope_options()


def update_dashboard_user(payload, current_username):
    username = str(payload.get("username", "")).strip().lower()
    role = str(payload.get("role", "")).strip().lower()
    scope_id = str(payload.get("scope_id", "")).strip()
    password = payload.get("password", "")
    active = payload.get("active", True) is True
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", username):
        raise ValueError("invalid username")
    if role == "client":
        role = "customer"
    if role not in {"admin", "controller", "customer", "operator"}:
        raise ValueError("invalid role")
    if role in {"admin", "operator"}:
        scope_id = ""
    elif not scope_id:
        raise ValueError("controller and customer roles require a scope")
    options = user_scope_options()
    valid_scopes = (
        {
            item["id"]
            for item in options["controllers" if role == "controller" else "customers"]
        }
        if role in {"controller", "customer"}
        else set()
    )
    if role in {"controller", "customer"} and scope_id not in valid_scopes:
        raise ValueError("scope does not exist")
    with _USERS_LOCK:
        users = load_users()
        existing = users.get(username)
        if not existing and (not isinstance(password, str) or len(password) < 8):
            raise ValueError("new users require a password with at least 8 characters")
        if password and (not isinstance(password, str) or len(password) < 8):
            raise ValueError("password must have at least 8 characters")
        if username == current_username and (role != "admin" or not active):
            raise ValueError("the current administrator cannot remove its own access")
        password_hash = (
            hash_password(password) if password else existing["password_hash"]
        )
        projected = users | {username: {"role": role, "active": active}}
        if not any(
            item["role"] == "admin" and item.get("active", True)
            for item in projected.values()
        ):
            raise ValueError("at least one active administrator is required")
        dashboard_repository().save_user(
            username,
            password_hash,
            role,
            scope_id or None,
            active,
        )
    return {"saved": True, "username": username}


def delete_dashboard_user(username, current_username):
    username = str(username).strip().lower()
    if username == current_username:
        raise ValueError("the current administrator cannot delete itself")
    with _USERS_LOCK:
        users = load_users()
        if username not in users:
            raise ValueError("user not found")
        remaining = {key: value for key, value in users.items() if key != username}
        if not any(
            item["role"] == "admin" and item.get("active", True)
            for item in remaining.values()
        ):
            raise ValueError("at least one active administrator is required")
        dashboard_repository().delete_user(username)
    return {"deleted": True, "username": username}


# =============================================================
# Dashboard State Engine
# =============================================================
class DashboardState:
    """
    Gerencia os arquivos JSON produzidos pelos Workers.
    Manages JSON files produced by Workers.
    """

    def __init__(self):
        self.files = STATE_FILES
        self.cache = {}
        self.cache_time = {}
        self.cache_ttl = 2

    def load(self, name):
        path = self.files.get(name)
        return read_json(path, {}) if path else {}

    def cached(self, name):
        now = time.time()
        if name in self.cache:
            if now - self.cache_time[name] < self.cache_ttl:
                return self.cache[name]
        data = self.load(name)
        self.cache[name] = data
        self.cache_time[name] = now
        return data

    def save(self, name, payload):
        path = self.files.get(name)
        if path:
            write_json(path, payload)
            self.cache[name] = payload
            self.cache_time[name] = time.time()


STATE = DashboardState()


def api_server_real():
    return read_json(STATE_FILES["server"], {"status": "unknown"})


def api_resources_real():
    data = read_json(STATE_FILES["metrics"], {})
    memory_free = float(data.get("memory", {}).get("free_pct", 0))
    memory_used = round(100 - memory_free, 1)

    return {
        "host": {"host_pct": float(data.get("cpu", {}).get("host_pct", 0))},
        "cpu": {
            "cpu_pct": float(data.get("cpu", {}).get("host_pct", 0)),
            "cores": data.get("cpu", {}).get("cores", 0),
        },
        "ram": {
            "ram_pct": data.get("memory", {}).get("used_pct", 0),
            "total_mb": data.get("memory", {}).get("total_mb", 0),
            "used_mb": data.get("memory", {}).get("used_mb", 0),
            "available_mb": data.get("memory", {}).get("available_mb", 0),
            "dayz_mb": data.get("memory", {}).get("dayz_mb", 0),
            "dayz_pct": data.get("memory", {}).get("dayz_pct", 0),
        },
        "disk": {
            "disk_pct": float(data.get("disk", {}).get("used_pct", 0)),
            "total_gb": data.get("disk", {}).get("total_gb", 0),
            "used_gb": data.get("disk", {}).get("used_gb", 0),
            "free_gb": data.get("disk", {}).get("free_gb", 0),
        },
        "network": data.get("network", {}),
        "temperature": data.get("temperature", {}),
        "updated_at": data.get("updated_at", 0),
    }


def api_mods_real():
    ok, data = run_api_script("mods.sh")
    if ok:
        return data
    return {
        "total": 0,
        "mods": [],
        "status": "ERROR",
        "message": data.get(
            "error", "Erro ao executar mods.sh | Error executing mods.sh"
        ),
    }


def api_backups_real():
    ok, data = run_api_script("backups.sh")
    if ok:
        return data
    return {
        "total": 0,
        "last_backup": "",
        "last_date": "",
        "total_size": "0 B",
        "status": "ERROR",
        "message": data.get(
            "error", "Erro ao executar backups.sh | Error executing backups.sh"
        ),
    }


def api_events_real():
    data = read_json(STATE_FILES["events"], [])
    if isinstance(data, dict):
        return data.get("events", [])
    return data


def api_current_operation():
    """Retorna o estado operacional atual do Installation Manager."""
    data = read_json(CURRENT_OPERATION_FILE, None)

    if not isinstance(data, dict) or not data:
        return {"status": "idle", "operation": None}

    return data



def api_log_viewer(
    user,
    source,
    server="",
    game="",
    instance="",
    limit=400,
):
    """
    Visualizador unificado de logs do Controller,
    Agent/Node e instância.

    Nenhum caminho arbitrário fornecido pelo usuário
    é aceito.
    """

    source = str(source or "controller").lower()

    try:
        limit = max(
            20,
            min(int(limit), 2000),
        )
    except (TypeError, ValueError):
        limit = 400

    candidates = []

    if source == "controller":
        if user.get("role") != "admin":
            raise PermissionError(
                "Somente administradores podem visualizar logs do Controller."
            )

        candidates = [
            DSM_ROOT / "logs" / "dashboard.log",
            DSM_ROOT / "logs" / "dsm-dashboard.service.log",
            DSM_ROOT / "logs" / "dsm.log",
        ]

    elif source in {"agent", "node"}:
        if not server or not game or not instance:
            raise ValueError(
                "Selecione Node, jogo e instância para identificar o Agent."
            )

        instance_path = (
            INSTANCE_ROOT
            / server
            / game
            / instance
        )

        if not can_access_instance(
            user,
            instance_path,
        ):
            raise PermissionError(
                "Acesso negado à instância."
            )

        candidates = [
            DSM_ROOT / "logs" / "metrics_worker.log",
            DSM_ROOT / "logs" / "monitor_worker.log",
            DSM_ROOT / "logs" / "server_worker.log",
            DSM_ROOT / "logs" / "dashboard_worker.log",
        ]

    elif source == "instance":
        if not server or not game or not instance:
            raise ValueError(
                "Selecione uma instância."
            )

        instance_path = (
            INSTANCE_ROOT
            / server
            / game
            / instance
        )

        if not can_access_instance(
            user,
            instance_path,
        ):
            raise PermissionError(
                "Acesso negado à instância."
            )

        candidates = [
            instance_path
            / "serverfiles"
            / "logs"
            / "latest.log",

            instance_path
            / "runtime"
            / "instance.log",
        ]

    else:
        raise ValueError(
            "Origem de log inválida."
        )

    selected = None

    for candidate in candidates:
        try:
            if candidate.is_file():
                selected = candidate
                break
        except OSError:
            continue

    if selected is None:
        return {
            "source": source,
            "file": None,
            "logs": [],
            "message": "Nenhum arquivo de log disponível para esta origem.",
        }

    try:
        with selected.open(
            "r",
            encoding="utf-8",
            errors="replace",
        ) as handle:
            lines = handle.readlines()
    except OSError as exc:
        return {
            "source": source,
            "file": selected.name,
            "logs": [],
            "error": str(exc),
        }

    return {
        "source": source,
        "file": selected.name,
        "logs": [
            line.rstrip("\r\n")
            for line in lines[-limit:]
        ],
        "total_returned": min(
            len(lines),
            limit,
        ),
    }


def api_logs():
    DAYZ_LOG_DIR = Path("/home/mine/steamcmd/serverfiles/profiles")
    if not DAYZ_LOG_DIR.exists():
        return {"logs": []}

    rpt_files = sorted(
        DAYZ_LOG_DIR.glob("*.RPT"), key=lambda x: x.stat().st_mtime, reverse=True
    )
    if not rpt_files:
        return {"logs": []}

    logfile = rpt_files[0]
    try:
        with logfile.open("r", encoding="utf-8", errors="ignore") as fp:
            lines = fp.readlines()
        return {"file": logfile.name, "logs": [line.rstrip() for line in lines[-100:]]}
    except Exception as exc:
        return {"error": str(exc), "logs": []}


def dashboard_summary():
    return {
        "dashboard": STATE.cached("dashboard"),
        "server": STATE.cached("server"),
        "metrics": STATE.cached("metrics"),
        "monitor": STATE.cached("monitor"),
        "alerts": STATE.cached("alerts"),
        "scheduler": STATE.cached("scheduler"),
        "events": STATE.cached("events"),
        "generated_at": int(time.time()),
    }


def dashboard_health():
    states = {key: path.exists() for key, path in STATE.files.items()}
    total = len(states)
    online = sum(1 for value in states.values() if value)
    score = int((online / total) * 100) if total > 0 else 0

    if score >= 90:
        status = "healthy"
    elif score >= 70:
        status = "warning"
    else:
        status = "critical"

    return {
        "score": score,
        "status": status,
        "states": states,
        "generated_at": int(time.time()),
    }


# =============================================================
# Execução de Scripts API | API Scripts Execution
# =============================================================
def run_api_script(script_name, *args, user=None, timeout=300):
    script = API_DIR / script_name
    if not script.exists():
        return False, {
            "error": f"script não encontrado: {script_name} | script not found: {script_name}"
        }

    env = os.environ.copy()
    env["DSM_ROOT"] = str(DSM_ROOT)
    if user:
        env["DSM_USER"] = user.get("username", "unknown")
        env["DSM_ROLE"] = user.get("role", "unknown")
    else:
        env["DSM_USER"] = env["DSM_ROLE"] = "system"

    try:
        process = subprocess.run(
            ["/bin/bash", str(script), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if process.returncode != 0:
            return False, {
                "error": process.stderr.strip() or process.stdout.strip(),
                "exit_code": process.returncode,
            }
        stdout = process.stdout.strip()
        if not stdout:
            return True, {}
        try:
            return True, json.loads(stdout)
        except json.JSONDecodeError:
            return True, {"result": stdout}
    except Exception as exc:
        return False, {"error": str(exc)}


def api_dispatch(route_name, *args, user=None):
    script_name = API_ROUTES.get(route_name)
    if not script_name:
        return None
    success, data = run_api_script(script_name, *args, user=user)
    return {"success": success, "data": data}


# =============================================================
# Notification Center
# =============================================================
class NotificationCenter:
    def __init__(self):
        self.queue_file = NOTIFICATION_QUEUE
        self.history_file = NOTIFICATION_HISTORY
        self.pending_flag = DISCORD_PENDING
        self.queue = read_json(self.queue_file, [])

    def save(self):
        write_json(self.queue_file, self.queue)

    def history(self):
        if not self.history_file.exists():
            return []
        with self.history_file.open("r", encoding="utf-8") as fp:
            return [line.rstrip() for line in fp.readlines()]

    def append_history(self, level, title, message):
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        entry = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{level.upper()}] {title} :: {message}\n"
        with self.history_file.open("a", encoding="utf-8") as fp:
            fp.write(entry)

    def push(self, level, title, message):
        item = {
            "timestamp": int(time.time()),
            "level": level,
            "title": title,
            "message": message,
            "sent": False,
        }
        self.queue.append(item)
        self.save()
        self.pending_flag.parent.mkdir(parents=True, exist_ok=True)
        self.pending_flag.touch(exist_ok=True)
        self.append_history(level, title, message)
        return item

    def clear(self):
        self.queue = []
        self.save()
        return {"status": "fila limpa | queue cleared"}

    def mark_sent(self):
        changed = False
        for item in self.queue:
            if not item.get("sent", False):
                item["sent"] = True
                changed = True
        if changed:
            self.save()
        if self.pending_flag.exists():
            self.pending_flag.unlink()


NOTIFICATIONS = NotificationCenter()


def notify(level, title, message):
    return NOTIFICATIONS.push(level, title, message)


def _dashboard_alert_item(alert):
    return {
        "id": alert["id"],
        "level": alert["level"],
        "title": alert.get("rule_id") or alert["id"],
        "message": alert.get("message", ""),
        "created": alert.get("opened_at"),
        "ack": alert.get("state") == "ACKNOWLEDGED",
    }


def _can_access_alert(
    user,
    alert,
    database_path=DATABASE_FILE,
):
    if not user or not alert:
        return False

    role = user.get("role")
    scope_id = user.get("scope_id", "")

    if role in {
        "admin",
        "operator",
    }:
        return True

    if role == "controller":
        return bool(
            scope_id
            and alert.get("controller_id")
            == scope_id
        )

    if role != "customer":
        return False

    instance_id = alert.get(
        "instance_id"
    )

    if (
        not scope_id
        or not instance_id
    ):
        return False

    row = dashboard_repository(database_path).instance_context(
        instance_id
    )

    return bool(
        row
        and row["customer_id"]
        == scope_id
    )


def _dashboard_active_alerts(
    user,
    database_path=DATABASE_FILE,
):
    if not user:
        return []

    role = user.get("role")
    scope_id = user.get("scope_id", "")

    if role in {
        "admin",
        "operator",
    }:
        return alert_store.list_active(
            Path(database_path),
        )

    if role == "controller":
        if not scope_id:
            return []

        return alert_store.list_active(
            Path(database_path),
            controller_id=scope_id,
        )

    if role != "customer":
        return []

    if not scope_id:
        return []

    active = alert_store.list_active(
        Path(database_path),
    )

    return [
        alert
        for alert in active
        if _can_access_alert(
            user,
            alert,
            database_path=database_path,
        )
    ]


def api_notifications(
    user=None,
    database_path=DATABASE_FILE,
):
    try:
        active = _dashboard_active_alerts(
            user,
            database_path=database_path,
        )

        alerts = [
            _dashboard_alert_item(alert)
            for alert in active
        ]

        return {
            "total": len(alerts),
            "critical": sum(
                1
                for alert in alerts
                if alert["level"] == "CRITICAL"
            ),
            "warning": sum(
                1
                for alert in alerts
                if alert["level"] == "WARNING"
            ),
            "alerts": alerts,
        }

    except Exception as exc:
        write_log(
            f"Falha ao carregar Alert Store "
            f"para o dashboard: {exc}"
        )

        return {
            "total": 0,
            "critical": 0,
            "warning": 0,
            "alerts": [],
            "error": str(exc),
        }


def _dashboard_alert_history(
    user,
    database_path=DATABASE_FILE,
):
    if not user:
        return []

    role = user.get("role")
    scope_id = user.get("scope_id", "")

    if role in {
        "admin",
        "operator",
    }:
        return alert_store.list_alerts(
            Path(database_path),
        )

    if role == "controller":
        if not scope_id:
            return []

        return alert_store.list_alerts(
            Path(database_path),
            controller_id=scope_id,
        )

    if role != "customer":
        return []

    if not scope_id:
        return []

    alerts = alert_store.list_alerts(
        Path(database_path),
    )

    return [
        alert
        for alert in alerts
        if _can_access_alert(
            user,
            alert,
            database_path=database_path,
        )
    ]


def api_notification_history(
    user=None,
    database_path=DATABASE_FILE,
):
    try:
        alerts = _dashboard_alert_history(
            user,
            database_path=database_path,
        )

        return {
            "total": len(alerts),
            "alerts": [
                {
                    **_dashboard_alert_item(alert),
                    "state": alert.get("state"),
                    "resolved": alert.get("resolved_at"),
                    "updated": alert.get("updated_at"),
                }
                for alert in alerts
            ],
        }

    except Exception as exc:
        write_log(
            f"Falha ao carregar historico de Alert Store "
            f"para o dashboard: {exc}"
        )

        return {
            "total": 0,
            "alerts": [],
            "error": str(exc),
        }


def api_notification_clear(
    user=None,
    database_path=DATABASE_FILE,
):
    try:
        active = _dashboard_active_alerts(
            user,
            database_path=database_path,
        )

        resolved = []

        for alert in active:
            result = alert_store.resolve_alert(
                Path(database_path),
                alert["id"],
            )

            if result is not None:
                resolved.append(
                    alert["id"]
                )

        return {
            "ok": True,
            "cleared": len(resolved),
            "ids": resolved,
        }

    except Exception as exc:
        write_log(
            f"Falha ao limpar Alert Store "
            f"para o dashboard: {exc}"
        )

        return {
            "ok": False,
            "cleared": 0,
            "ids": [],
            "error": str(exc),
        }


def dispatch_discord_notifications():
    if not DISCORD_PENDING.exists():
        return
    success, _ = run_api_script("discord.sh", "worker")
    if success:
        NOTIFICATIONS.mark_sent()


def notification_worker():
    while True:
        try:
            dispatch_discord_notifications()
        except Exception as exc:
            write_log(f"Notification worker error: {exc}")
        time.sleep(10)


# =============================================================
# HTTP Handler
# =============================================================
class DashboardHandler(BaseHTTPRequestHandler):
    server_version = SERVER_NAME

    def log_message(self, fmt, *args):
        pass

    def send_json(self, code, payload):
        body = json.dumps(payload, indent=4, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        if not path.exists():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(path))[0] or DEFAULT_CONTENT_TYPE
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def unauthorized(self):
        self.send_json(
            401,
            {"error": "Autenticação necessária | Authentication required"},
        )

    def forbidden(self):
        self.send_json(403, {"error": "Acesso negado | Access denied"})

    def read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length <= 0 or length > MAX_JSON_BODY:
            raise ValueError("JSON body is empty or too large")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def catalog_request_file(self, request):
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="dsm-catalog-",
            delete=False,
        )
        try:
            json.dump(request, handle, ensure_ascii=False)
            handle.write("\n")
            return handle.name
        finally:
            handle.close()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in STATIC_FILES and STATIC_FILES[path].exists():
            self.send_response(200)
            self.send_header(
                "Content-Type",
                mimetypes.guess_type(str(STATIC_FILES[path]))[0]
                or DEFAULT_CONTENT_TYPE,
            )
            self.end_headers()
            return
        self.send_error(404, "Not Found")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        public_files = {
            "/login.html",
            "/index.html",
            "/auth.js",
            "/app.js",
            "/style.css",
            "/installation-events.js",
            "/installation-events.css",
            "/catalog-v2.js",
            "/catalog-v2.css",
            "/css/alerts.css",
            "/css/infrastructure-explorer.css",
            "/css/infrastructure-shell.css",
            "/css/infrastructure-details.css",
            "/js/notifications.js",
            "/js/dashboard-state.js",
            "/js/infrastructure-explorer.js",
            "/js/infrastructure-details.js",
            "/js/infrastructure-shell.js",
            "/customer.html",
            "/customer.js",
            "/customer.css",
            "/customer-delete.css",
            "/customer-instance.html",
            "/customer-instance.js",
            "/contract-demo.html",
            "/contract-demo.js",
            "/runtime-selector.js",
            "/theme.js",
            "/components/header.html",
            "/components/sidebar.html",
            "/components/cards.html",
            "/components/alerts.html",
            "/favicon.ico",
        }
        if path in public_files and path in STATIC_FILES:
            self.send_file(STATIC_FILES[path])
            return

        if path == "/health":
            self.send_json(200, dashboard_health())
            return

        if path == "/ping":
            self.send_json(200, {"status": "ok", "generated_at": int(time.time())})
            return

        user = authenticate(self.headers)
        if not can_read(user):
            self.unauthorized()
            return

        if path in STATIC_FILES:
            self.send_file(STATIC_FILES[path])
            return

        if path == "/api/log-viewer":
            query = parse_qs(parsed.query)

            try:
                result = api_log_viewer(
                    user,
                    query.get("source", ["controller"])[0],
                    query.get("server", [""])[0],
                    query.get("game", [""])[0],
                    query.get("instance", [""])[0],
                    query.get("limit", ["400"])[0],
                )
            except PermissionError as exc:
                self.send_json(
                    403,
                    {"error": str(exc)},
                )
                return
            except ValueError as exc:
                self.send_json(
                    400,
                    {"error": str(exc)},
                )
                return

            self.send_json(
                200,
                result,
            )
            return

        # Runtime Multi Server
        if path == "/api/runtime":
            query = parse_qs(parsed.query)
            server = query.get("server", ["server01"])[0]
            game = query.get("game", ["dayz"])[0]
            instance = query.get("instance", ["survival01"])[0]
            instance_path = INSTANCE_ROOT / server / game / instance
            if not can_access_instance(user, instance_path):
                self.forbidden()
                return
            self.send_json(200, api_runtime_summary(server, game, instance))
            return

        if path == "/api/runtime/list":
            resources = api_runtime_list()
            if user["role"] != "admin":
                resources = [
                    item
                    for item in resources
                    if can_access_instance(
                        user,
                        INSTANCE_ROOT
                        / item.get("server", "")
                        / item.get("game", "")
                        / item.get("instance", ""),
                    )
                ]
            self.send_json(200, resources)
            return

        if path == "/api/instance/config":
            query = parse_qs(parsed.query)
            try:
                instance = catalog_instance_path(query.get("instance", [""])[0])
                if not has_instance_permission(user, instance, "game.files.read"):
                    self.forbidden()
                    return
                relative = query.get("file", [""])[0]
                if not relative:
                    self.send_json(200, {"files": list_instance_configs(instance)})
                    return
                config = instance_config_path(instance, relative)
                if not config.is_file():
                    self.send_json(
                        404, {"error": "Arquivo de configuração não encontrado"}
                    )
                    return
                self.send_json(
                    200,
                    {
                        "file": relative,
                        "content": config.read_text(encoding="utf-8", errors="replace"),
                    },
                )
            except (ValueError, OSError) as exc:
                self.send_json(400, {"error": str(exc)})
            return

        if path in {
            "/api/instance/logs",
            "/api/instance/files",
            "/api/instance/files/search",
            "/api/instance/file",
            "/api/instance/file/text",
            "/api/instance/backups",
            "/api/instance/provision",
        }:
            query = parse_qs(parsed.query)
            try:
                instance = instance_identity_path(
                    query.get("server", [""])[0],
                    query.get("game", [""])[0],
                    query.get("instance", [""])[0],
                )
                required = {
                    "/api/instance/logs": "logs.read",
                    "/api/instance/files": "files.list",
                    "/api/instance/files/search": "files.list",
                    "/api/instance/file": "files.download",
                    "/api/instance/file/text": "game.files.read",
                    "/api/instance/backups": "backup.list",
                    "/api/instance/provision": "instance.view",
                }[path]
                if not has_instance_permission(user, instance, required):
                    self.forbidden()
                    return
                if path == "/api/instance/logs":
                    try:
                        limit = int(query.get("limit", ["200"])[0])
                    except ValueError:
                        limit = 200
                    self.send_json(200, instance_logs(instance, limit))
                elif path == "/api/instance/files":
                    self.send_json(
                        200,
                        {
                            "path": query.get("path", ["."])[0],
                            "entries": list_instance_files(
                                instance,
                                query.get("path", ["."])[0],
                            ),
                        },
                    )
                elif path == "/api/instance/files/search":
                    term = query.get(
                        "q",
                        [""],
                    )[0]

                    if not term.strip():
                        self.send_json(
                            200,
                            {
                                "query": "",
                                "results": [],
                            },
                        )
                        return

                    try:
                        limit = int(
                            query.get(
                                "limit",
                                ["200"],
                            )[0]
                        )
                    except ValueError:
                        limit = 200

                    results = search_instance_files(
                        instance,
                        term,
                        limit,
                    )

                    self.send_json(
                        200,
                        {
                            "query": term,
                            "total": len(results),
                            "results": results,
                        },
                    )
                elif path == "/api/instance/file/text":
                    relative_path = query.get(
                        "path",
                        [""],
                    )[0]
                    self.send_json(
                        200,
                        read_instance_text_file(
                            instance,
                            relative_path,
                        ),
                    )
                elif path == "/api/instance/file":
                    file_path = instance_file_path(
                        instance,
                        query.get("path", [""])[0],
                    )
                    if not file_path.is_file():
                        raise ValueError("path is not a file")
                    self.send_file(file_path)
                elif path == "/api/instance/provision":
                    relative = Path(instance).relative_to(INSTANCE_ROOT).parts
                    self.send_json(
                        200,
                        read_json(
                            DSM_ROOT
                            / "runtime"
                            / "resources"
                            / relative[0]
                            / relative[1]
                            / relative[2]
                            / "provision.json",
                            {
                                "status": "offline",
                                "stage": "completed",
                                "progress": 100,
                            },
                        ),
                    )
                else:
                    self.send_json(
                        200,
                        {
                            "backups": list_instance_backups(
                                instance,
                            )
                        },
                    )
            except (
                ValueError,
                OSError,
                tarfile.TarError,
            ) as exc:
                self.send_json(
                    400,
                    {"error": str(exc)},
                )
            return

        if path == "/api/instance/agents":
            self.send_json(200, {"agents": customer_agents(user)})
            return

        if path.startswith("/api/infrastructure"):
            backend = dashboard_repository(
                DATABASE_FILE
            ).backend

            result = dispatch_infrastructure_get(
                path,
                parsed.query,
                user=user,
                backend=backend,
            )

            if result is not None:
                status, payload = result
                self.send_json(
                    status,
                    payload,
                )
                return

        if path == "/api/agents":
            try:
                backend = dashboard_repository(
                    DATABASE_FILE
                ).backend

                self.send_json(
                    200,
                    {
                        "agents": list_agents_for_user(
                            user,
                            backend,
                        )
                    },
                )
            except PermissionError as exc:
                self.send_json(
                    403,
                    {"error": str(exc)},
                )
            return

        if path == "/api/agent/ports":
            query = parse_qs(
                parsed.query
            )

            try:
                backend = dashboard_repository(
                    DATABASE_FILE
                ).backend

                result = agent_ports_for_user(
                    user,
                    backend,
                    query.get(
                        "agent_id",
                        [""],
                    )[0],
                )

                self.send_json(
                    200,
                    result,
                )

            except PermissionError as exc:
                self.send_json(
                    403,
                    {"error": str(exc)},
                )

            except ValueError as exc:
                self.send_json(
                    400,
                    {"error": str(exc)},
                )

            return

        if path == "/api/customer/regions":
            try:
                backend = dashboard_repository(
                    DATABASE_FILE
                ).backend

                result = region_options_for_user(
                    user,
                    backend,
                )

                self.send_json(
                    200,
                    result,
                )

            except PermissionError as exc:
                self.send_json(
                    403,
                    {"error": str(exc)},
                )

            except (
                ValueError,
                RuntimeError,
            ) as exc:
                self.send_json(
                    400,
                    {"error": str(exc)},
                )

            return

        if path == "/api/customer/contracts":
            self.send_json(200, {"contracts": customer_contracts(user)})
            return

        if path == "/api/users":
            if user["role"] != "admin":
                self.forbidden()
                return
            self.send_json(
                200, {"users": public_users(), "scopes": user_scope_options()}
            )
            return

        # =============================================================
        # Timeline Universal
        # =============================================================
        if path == "/api/timeline":
            query = parse_qs(parsed.query)

            try:
                limit = int(query.get("limit", ["50"])[0])
            except (ValueError, TypeError):
                limit = 50

            limit = max(1, min(limit, 1000))
            history_file = DSM_ROOT / "runtime" / "events" / "history.json"
            events = read_json(history_file, [])

            if not isinstance(events, list):
                events = []

            events.sort(
                key=lambda event: event.get("timestamp", event.get("time", 0)),
                reverse=True,
            )

            self.send_json(200, events[:limit])
            return

        # =============================================================
        # Operation State
        # =============================================================
        if path == "/api/operations/current":
            self.send_json(200, api_current_operation())
            return

        if path.startswith("/api/catalog/"):
            query = parse_qs(parsed.query)
            action = path.removeprefix("/api/catalog/")
            try:
                if action == "search":
                    search = query.get("q", [""])[0].strip()
                    game = query.get("game", ["minecraft"])[0].strip().lower()
                    version = query.get("version", [""])[0].strip()
                    loader = query.get("loader", [""])[0].strip().lower()
                    content_type = query.get("type", ["mod"])[0].strip().lower()

                    try:
                        limit = int(
                            query.get(
                                "limit",
                                ["20"],
                            )[0]
                        )
                    except ValueError:
                        limit = 20

                    limit = max(
                        1,
                        min(
                            limit,
                            50,
                        ),
                    )

                    if not search:
                        self.send_json(
                            400,
                            {
                                "error": "Informe um termo de busca."
                            },
                        )
                        return

                    if game != "minecraft":
                        self.send_json(
                            400,
                            {
                                "error":
                                    "Busca externa disponível inicialmente para Minecraft."
                            },
                        )
                        return

                    if content_type not in {
                        "mod",
                        "plugin",
                        "modpack",
                    }:
                        self.send_json(
                            400,
                            {
                                "error":
                                    "Tipo de conteúdo inválido."
                            },
                        )
                        return

                    success, data = catalog_api(
                        "search",
                        "modrinth",
                        search,
                        game,
                        version,
                        loader,
                        content_type,
                        str(limit),
                        user=user,
                    )

                elif action == "runtimes":
                    success, data = catalog_api(
                        "runtimes", query.get("game", [""])[0], user=user
                    )
                elif action == "runtime":
                    success, data = catalog_api(
                        "runtime", query.get("id", [""])[0], user=user
                    )
                elif action == "versions":
                    success, data = catalog_api(
                        "versions", query.get("runtime", [""])[0], user=user
                    )
                elif action == "builds":
                    success, data = catalog_api(
                        "builds",
                        query.get("runtime", [""])[0],
                        query.get("version", [""])[0],
                        user=user,
                    )
                elif action == "content":
                    success, data = catalog_api(
                        "content", query.get("game", [""])[0], user=user
                    )
                elif action == "content-definition":
                    success, data = catalog_api(
                        "content-definition", query.get("id", [""])[0], user=user
                    )
                elif action == "providers":
                    success, data = catalog_api("providers", user=user)
                elif action == "installed":
                    instance = catalog_instance_path(query.get("instance", [""])[0])
                    if not can_access_instance(user, instance):
                        self.forbidden()
                        return
                    success, data = catalog_api("installed", instance, user=user)
                else:
                    self.send_error(404, "Not Found")
                    return
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            self.send_json(200 if success else 422, data)
            return

        endpoints = {
            "/api/whoami": lambda: {"username": user["username"], "role": user["role"]},
            "/api/server": api_server_real,
            "/api/resources": api_resources_real,
            "/api/mods": api_mods_real,
            "/api/backups": api_backups_real,
            "/api/events": api_events_real,
            "/api/logs": api_logs,
            "/api/dashboard/summary": dashboard_summary,
            "/api/health": dashboard_health,
            "/api/notifications": lambda: api_notifications(
                user,
                database_path=DATABASE_FILE,
            ),
            "/api/notifications/clear": lambda: api_notification_clear(
                user,
                database_path=DATABASE_FILE,
            ),
            "/api/notifications/history": lambda: api_notification_history(
                user,
                database_path=DATABASE_FILE,
            ),
        }

        if path in endpoints:
            self.send_json(200, endpoints[path]())
            return

        if path.startswith("/api/"):
            route = path.replace("/api/", "")
            result = api_dispatch(route, user=user)
            if result is not None:
                self.send_json(200, result)
                return

        self.send_error(404, "Not Found")

    def do_POST(self):
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        if not can_write(user):
            self.forbidden()
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/agent/location":
            try:
                body = self.read_json_body()

                backend = dashboard_repository(
                    DATABASE_FILE
                ).backend

                result = dispatch_agent_location_post(
                    path,
                    body,
                    user=user,
                    backend=backend,
                )

                if result is not None:
                    status, payload = result
                    self.send_json(
                        status,
                        payload,
                    )
                    return
            except ValueError as exc:
                self.send_json(
                    400,
                    {"error": str(exc)},
                )
                return

        if path == "/api/agent/ports/set":
            try:
                body = self.read_json_body()

                backend = dashboard_repository(
                    DATABASE_FILE
                ).backend

                result = set_agent_ports_for_user(
                    user,
                    backend,
                    body,
                )

                self.send_json(
                    200,
                    result,
                )

            except PermissionError as exc:
                self.send_json(
                    403,
                    {"error": str(exc)},
                )

            except (
                ValueError,
                RuntimeError,
            ) as exc:
                self.send_json(
                    400,
                    {"error": str(exc)},
                )

            return

        if path == "/api/acknowledge":
            query = parse_qs(parsed.query)
            alert_id = query.get("id", [""])[0].strip()

            if not alert_id:
                self.send_json(
                    400,
                    {"ok": False, "error": "id obrigatório"},
                )
                return

            try:
                alert = alert_store.get_alert(
                    Path(DATABASE_FILE),
                    alert_id,
                )

                if alert is None:
                    self.send_json(
                        422,
                        {
                            "ok": False,
                            "id": alert_id,
                            "error": "alert not found",
                        },
                    )
                    return

                if not _can_access_alert(
                    user,
                    alert,
                    database_path=DATABASE_FILE,
                ):
                    self.forbidden()
                    return

                result = alert_store.acknowledge_alert(
                    Path(DATABASE_FILE),
                    alert_id,
                )

                self.send_json(
                    200,
                    {
                        "ok": True,
                        "id": alert_id,
                        "result": result,
                    },
                )

            except ValueError as exc:
                self.send_json(
                    422,
                    {
                        "ok": False,
                        "id": alert_id,
                        "error": str(exc),
                    },
                )

            except Exception as exc:
                write_log(
                    f"Falha ao reconhecer alerta "
                    f"{alert_id}: {exc}"
                )

                self.send_json(
                    500,
                    {
                        "ok": False,
                        "id": alert_id,
                        "error": "internal alert store error",
                    },
                )

            return

        if path == "/api/instance/config":
            try:
                body = self.read_json_body()
                instance = catalog_instance_path(body.get("instance", ""))
                if not has_instance_permission(user, instance, "game.files.write"):
                    self.forbidden()
                    return
                content = body.get("content")
                if (
                    not isinstance(content, str)
                    or len(content.encode("utf-8")) > MAX_INSTANCE_CONFIG
                ):
                    raise ValueError("invalid or oversized config content")
                config = instance_config_path(instance, body.get("file", ""))
                if not config.is_file():
                    raise ValueError("config file must already exist")
                config.write_text(content, encoding="utf-8")
                self.send_json(200, {"saved": True, "file": body.get("file")})
            except (ValueError, OSError) as exc:
                self.send_json(400, {"error": str(exc)})
            return

        if path == "/api/instance/create":
            try:
                body = self.read_json_body()
                result = create_customer_instance(user, body)
                self.send_json(201, result)
            except PermissionError as exc:
                self.send_json(403, {"error": str(exc)})
            except (ValueError, OSError, sqlite3.Error) as exc:
                self.send_json(400, {"error": str(exc)})
            return

        if path in {
            "/api/instance/start",
            "/api/instance/stop",
            "/api/instance/restart",
        }:
            try:
                body = self.read_json_body()
                instance = instance_identity_path(
                    body.get("server", ""),
                    body.get("game", ""),
                    body.get("instance", ""),
                )
                if not has_instance_permission(user, instance, "instance.control"):
                    self.forbidden()
                    return
                action = path.rsplit("/", 1)[-1]
                success, result = control_instance(user, instance, action)
                self.send_json(200 if success else 422, result)
            except (ValueError, OSError) as exc:
                self.send_json(400, {"error": str(exc)})
            return

        if path == "/api/instance/file/text":
            try:
                body = self.read_json_body()

                instance = instance_identity_path(
                    body.get("server", ""),
                    body.get("game", ""),
                    body.get("instance", ""),
                )

                if not has_instance_permission(
                    user,
                    instance,
                    "game.files.write",
                ):
                    self.forbidden()
                    return

                relative_path = body.get(
                    "path",
                    "",
                )

                result = write_instance_text_file(
                    instance,
                    relative_path,
                    body.get("content", ""),
                )

                audit(
                    user,
                    "files.edit",
                    "success",
                    Path(instance).name,
                    relative_path,
                )

                self.send_json(
                    200,
                    result,
                )

            except (ValueError, OSError) as exc:
                self.send_json(
                    400,
                    {"error": str(exc)},
                )

            return

        if path == "/api/instance/directory/create":
            try:
                body = self.read_json_body()
                instance = instance_identity_path(
                    body.get("server", ""),
                    body.get("game", ""),
                    body.get("instance", ""),
                )

                if not has_instance_permission(user, instance, "files.mkdir"):
                    self.forbidden()
                    return

                result = create_instance_directory(
                    instance,
                    body.get("path", "."),
                    body.get("name", ""),
                )

                audit(
                    user,
                    "files.directory.create",
                    "success",
                    Path(instance).name,
                    result["path"],
                )

                self.send_json(
                    201,
                    result,
                )
            except (ValueError, OSError) as exc:
                self.send_json(400, {"error": str(exc)})
            return

        if path in {"/api/instance/file/upload", "/api/instance/file/delete"}:
            try:
                body = self.read_json_body()
                instance = instance_identity_path(
                    body.get("server", ""),
                    body.get("game", ""),
                    body.get("instance", ""),
                )
                permission = (
                    "files.upload" if path.endswith("upload") else "files.delete"
                )
                if not has_instance_permission(user, instance, permission):
                    self.forbidden()
                    return
                if path.endswith("upload"):
                    name = str(body.get("name", ""))
                    if (
                        not name
                        or Path(name).name != name
                        or name in PROTECTED_INSTANCE_PARTS
                    ):
                        raise ValueError("invalid upload name")
                    raw = base64.b64decode(str(body.get("content", "")), validate=True)
                    if not raw or len(raw) > MAX_INSTANCE_FILE:
                        raise ValueError("empty or oversized upload")
                    directory = instance_file_path(instance, body.get("path", "."))
                    if not directory.is_dir():
                        raise ValueError("upload destination is not a directory")
                    destination = instance_file_path(
                        instance,
                        str(Path(body.get("path", ".")) / name),
                        allow_missing=True,
                    )
                    if destination.exists():
                        raise ValueError("a file with this name already exists")
                    destination.write_bytes(raw)
                    audit(
                        user,
                        "files.upload",
                        "success",
                        Path(instance).name,
                        str(destination.relative_to(instance)),
                    )
                    self.send_json(201, {"uploaded": True, "name": name})
                else:
                    target = instance_file_path(
                        instance,
                        body.get("path", ""),
                    )

                    game_root = game_files_root(
                        instance,
                    ).resolve()

                    if target.resolve() == game_root:
                        raise ValueError("cannot delete the game files root")

                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                    audit(
                        user,
                        "files.delete",
                        "success",
                        Path(instance).name,
                        body.get("path", ""),
                    )
                    self.send_json(
                        200,
                        {"deleted": True},
                    )
            except (ValueError, OSError, binascii.Error) as exc:
                self.send_json(400, {"error": str(exc)})
            return

        if path in {
            "/api/instance/backup/create",
            "/api/instance/backup/restore",
            "/api/instance/backup/delete",
        }:
            try:
                body = self.read_json_body()
                instance = instance_identity_path(
                    body.get("server", ""),
                    body.get("game", ""),
                    body.get("instance", ""),
                )
                action = path.rsplit("/", 1)[-1]
                if not has_instance_permission(user, instance, f"backup.{action}"):
                    self.forbidden()
                    return
                if action == "create":
                    result = create_instance_backup(instance)
                elif action == "restore":
                    result = restore_instance_backup(
                        user, instance, body.get("name", "")
                    )
                else:
                    backup = instance_backup_path(instance, body.get("name", ""))
                    backup.unlink()
                    audit(
                        user,
                        "backup.delete",
                        "success",
                        Path(instance).name,
                        backup.name,
                    )
                    result = {"deleted": True, "name": backup.name}
                if action == "create":
                    audit(
                        user,
                        "backup.create",
                        "success",
                        Path(instance).name,
                        result["name"],
                    )
                self.send_json(200 if action != "create" else 201, result)
            except (ValueError, OSError, tarfile.TarError) as exc:
                self.send_json(400, {"error": str(exc)})
            return

        if path == "/api/instance/provision/retry":
            try:
                body = self.read_json_body()

                instance = instance_identity_path(
                    body.get("server", ""),
                    body.get("game", ""),
                    body.get("instance", ""),
                )

                if not has_instance_permission(
                    user,
                    instance,
                    "instance.provision.retry",
                ):
                    self.forbidden()
                    return

                result = retry_instance_provisioning(
                    user,
                    instance,
                )

                self.send_json(
                    202,
                    result,
                )

            except PermissionError as exc:
                self.send_json(
                    403,
                    {"error": str(exc)},
                )

            except (
                ValueError,
                OSError,
                sqlite3.Error,
            ) as exc:
                self.send_json(
                    400,
                    {"error": str(exc)},
                )

            return

        if path == "/api/instance/reinstall":
            try:
                body = self.read_json_body()

                server = str(
                    body.get("server", "")
                ).strip()

                game = str(
                    body.get("game", "")
                ).strip().lower()

                instance = str(
                    body.get("instance", "")
                ).strip()

                preserve_config = bool(
                    body.get(
                        "preserve_config",
                        True,
                    )
                )

                if not all(
                    (
                        server,
                        game,
                        instance,
                    )
                ):
                    raise ValueError(
                        "server, game e instance são obrigatórios."
                    )

                result = reinstall_instance_from_game_data(
                    user,
                    server,
                    game,
                    instance,
                    preserve_config=preserve_config,
                )

                self.send_json(
                    200,
                    result,
                )

            except PermissionError as exc:
                self.send_json(
                    403,
                    {
                        "error": str(exc),
                    },
                )

            except (
                ValueError,
                OSError,
                sqlite3.Error,
            ) as exc:
                self.send_json(
                    400,
                    {
                        "error": str(exc),
                    },
                )

            return

        if path == "/api/instance/delete":
            try:
                body = self.read_json_body()
                instance = instance_identity_path(
                    body.get("server", ""),
                    body.get("game", ""),
                    body.get("instance", ""),
                )
                if not has_instance_permission(user, instance, "instance.delete"):
                    self.forbidden()
                    return
                if body.get("confirmation") != Path(instance).name:
                    raise ValueError("instance identifier confirmation does not match")
                self.send_json(
                    200,
                    delete_instance(user, instance, body.get("final_backup") is True),
                )
            except (ValueError, OSError, sqlite3.Error, tarfile.TarError) as exc:
                self.send_json(400, {"error": str(exc)})
            return

        if path in {"/api/users/save", "/api/users/delete"}:
            if user["role"] != "admin":
                self.forbidden()
                return
            try:
                body = self.read_json_body()
                result = (
                    update_dashboard_user(body, user["username"])
                    if path.endswith("/save")
                    else delete_dashboard_user(
                        body.get("username", ""), user["username"]
                    )
                )
                self.send_json(200, result)
            except (ValueError, OSError, sqlite3.Error) as exc:
                self.send_json(400, {"error": str(exc)})
            return

        if path.startswith("/api/catalog/"):
            action = path.removeprefix("/api/catalog/")
            temp_request = None
            try:
                body = self.read_json_body()
                if action in {"compatibility", "plan", "install"}:
                    request = body.get("request", body)
                    if not isinstance(request, dict):
                        raise ValueError("request must be an object")
                    temp_request = self.catalog_request_file(request)
                if action == "compatibility":
                    success, result = catalog_api(
                        "compatibility", temp_request, user=user
                    )
                elif action == "environment-install":
                    if user["role"] != "admin":
                        self.forbidden()
                        return
                    environment_id = body.get("environment_id", "")
                    selector = body.get("selector", "current")
                    if not isinstance(environment_id, str) or not re.fullmatch(
                        r"[a-z0-9][a-z0-9._-]{0,127}", environment_id
                    ):
                        raise ValueError("valid environment_id is required")
                    if not isinstance(selector, str) or not re.fullmatch(
                        r"[A-Za-z0-9._-]{1,128}", selector
                    ):
                        raise ValueError("valid selector is required")
                    success, result = catalog_api(
                        "environment-install", environment_id, selector, user=user
                    )
                elif action in {"plan", "install"}:
                    instance = catalog_instance_path(body.get("instance", ""))
                    if not can_access_instance(user, instance, write=True):
                        self.forbidden()
                        return
                    success, result = catalog_api(
                        action, temp_request, instance, user=user
                    )
                elif action == "remove":
                    instance = catalog_instance_path(body.get("instance", ""))
                    if not can_access_instance(user, instance, write=True):
                        self.forbidden()
                        return
                    content_id = body.get("content_id", "")
                    if not isinstance(content_id, str) or not content_id:
                        raise ValueError("content_id is required")
                    success, result = catalog_api(
                        "remove", instance, content_id, user=user
                    )
                elif action in {"verify", "rollback"}:
                    instance = catalog_instance_path(body.get("instance", ""))
                    if not can_access_instance(user, instance, write=True):
                        self.forbidden()
                        return
                    success, result = catalog_api(action, instance, user=user)
                else:
                    self.send_error(404, "Not Found")
                    return
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            finally:
                if temp_request:
                    try:
                        Path(temp_request).unlink(missing_ok=True)
                    except OSError:
                        pass
            self.send_json(200 if success else 422, result)
            return

        if path in POST_ROUTES:
            action = POST_ROUTES[path]
            success, result = run_api_script("server.sh", action, user=user)
            self.send_json(200 if success else 500, result)
            return

        self.send_error(404, "Not Found")


# =============================================================
# Servidor e Execução | Server and Execution
# =============================================================
class DashboardServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, DashboardHandler)
        self.started = time.time()

    @property
    def uptime(self):
        return int(time.time() - self.started)


def validate_environment():
    required = [DASHBOARD_DIR, WEB_DIR, API_DIR, WORKERS_DIR, STATE_DIR, CONFIG_DIR]
    missing = [str(directory) for directory in required if not directory.exists()]
    if missing:
        print(
            "\nErro de inicialização DSM Dashboard | DSM Dashboard initialization error"
        )
        for item in missing:
            print(f" - {item}")
        raise SystemExit(1)


def print_banner():
    print("=" * 60)
    print(f" {SERVER_NAME}\n{'=' * 60}")
    print(f" DSM ROOT : {DSM_ROOT}\n WEB      : {WEB_DIR}\n API      : {API_DIR}")
    print(f" HOST     : {HOST}\n PORTA | PORT : {PORT}\n" + "=" * 60)


def run():
    validate_environment()
    print_banner()
    server = DashboardServer((HOST, PORT))
    threading.Thread(target=notification_worker, daemon=True).start()
    try:
        print(f"Acesse | Access: http://{HOST}:{PORT}\n")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando DSM Dashboard... | Shutting down DSM Dashboard...")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
