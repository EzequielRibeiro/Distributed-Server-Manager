#!/usr/bin/env python3
"""Administrative preview and explicit confirmation for post-migration Storage Pool source cleanup."""
from __future__ import annotations
from urllib.parse import parse_qs, urlparse

from instance_storage_pool_migration_repository import InstanceStoragePoolMigrationRepository

PATH = "/api/admin/instance/storage-pool-cleanup"


def _role(user):
    return str((user or {}).get("role") or "").strip().lower()


def install_storage_pool_source_cleanup(legacy, authenticate):
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def authenticated_admin(self):
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return None
        if _role(user) != "admin":
            self.send_json(403, {"error": "forbidden", "message": "Storage Pool source cleanup requires admin role."})
            return None
        return user

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path != PATH:
            return previous_get(self)
        user = authenticated_admin(self)
        if user is None:
            return
        try:
            values = parse_qs(parsed.query or "")
            migration_id = str((values.get("migration_id") or [""])[0]).strip()
            if not migration_id:
                raise ValueError("migration_id is required")
            repo = InstanceStoragePoolMigrationRepository(backend())
            repo.initialize()
            self.send_json(200, {"cleanup": repo.cleanup_preview(migration_id)})
        except KeyError as exc:
            self.send_json(404, {"error": "not_found", "message": str(exc)})
        except (ValueError, TypeError) as exc:
            self.send_json(400, {"error": "invalid_request", "message": str(exc)})
        except Exception:
            self.send_json(500, {"error": "storage_pool_cleanup_failed", "message": "Falha ao validar a cópia de origem."})

    def do_post(self):
        parsed = urlparse(self.path)
        if parsed.path != PATH:
            return previous_post(self)
        user = authenticated_admin(self)
        if user is None:
            return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."})
            return
        try:
            source_migration_id = str((payload or {}).get("source_migration_id") or "").strip()
            confirmation = str((payload or {}).get("confirmation") or "").strip()
            repo = InstanceStoragePoolMigrationRepository(backend())
            repo.initialize()
            state = repo.enqueue_cleanup(
                source_migration_id=source_migration_id,
                confirmation=confirmation,
                requested_by=str(user.get("username") or "system"),
            )
            self.send_json(202, {"cleanup": state})
        except KeyError as exc:
            self.send_json(404, {"error": "not_found", "message": str(exc)})
        except (ValueError, TypeError) as exc:
            self.send_json(400, {"error": "invalid_request", "message": str(exc)})
        except Exception:
            self.send_json(500, {"error": "storage_pool_cleanup_failed", "message": "Falha ao solicitar limpeza da origem."})

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = ["PATH", "install_storage_pool_source_cleanup"]
