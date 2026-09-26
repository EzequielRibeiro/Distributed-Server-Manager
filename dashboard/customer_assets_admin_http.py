#!/usr/bin/env python3
"""Bounded edits for contracts and instance labels in the Customer admin page.

Runtime, placement, agent and instance resource limits are intentionally
immutable here: they require separate migration / billing workflows.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from alert_repository import AlertSession, dialect_for_backend
from core.catalog_resource_profile_policy import resolve_catalog_resource_profile
from customer_audit import audit_customer_event
from customer_management_repository import CustomerManagementRepository
from runtime_workspace_catalog import game_workspace_catalog

PATH = "/api/admin/customer/assets"
ROOT = Path(__file__).resolve().parents[1]
CONTRACT_STATUS = frozenset({"pending", "active", "suspended", "cancelled", "expired"})
CONTRACT_FIELDS = frozenset({"status", "instance_limit", "ends_at", "resource_profile_id", "product_variant"})
INSTANCE_FIELDS = frozenset({"name"})


def authorize(user, customer):
    role = str((user or {}).get("role") or "").lower()
    if role == "admin":
        return
    if role == "controller" and user.get("scope_id") and str(user["scope_id"]) == str(customer.get("controller_id") or ""):
        return
    raise PermissionError("Somente o administrador ou o Controller responsável pode editar estes dados.")


def _metadata(raw):
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        value = json.loads(raw or "{}")
        if isinstance(value, dict):
            return value
    raise ValueError("Metadados do contrato inválidos.")


def _expiry(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            date.fromisoformat(raw)
        else:
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Data inválida: informe AAAA-MM-DD ou uma data ISO 8601.") from exc
    return raw


def edit_customer_asset(payload, *, user, backend, root=ROOT):
    if not isinstance(payload, dict):
        raise ValueError("Dados inválidos.")
    action = str(payload.get("action") or "")
    code = str(payload.get("customer_code") or "").strip().upper()
    identifier = str(payload.get("id") or "").strip()
    changes = payload.get("changes") or {}
    if not code or not identifier:
        raise ValueError("Cliente e identificador são obrigatórios.")
    if action != "delete_contract" and (not isinstance(changes, dict) or not changes):
        raise ValueError("Informe pelo menos uma alteração.")
    customer = CustomerManagementRepository(backend).detail(code)["customer"]
    authorize(user, customer)
    customer_id = int(customer["id"])
    ph = dialect_for_backend(backend).placeholder
    now = dialect_for_backend(backend).current_timestamp
    backend.initialize()
    event = None
    with backend.transaction() as connection:
        session = AlertSession(backend, connection)
        try:
            if action in {"edit_contract", "delete_contract"}:
                row = session.execute(
                    f"SELECT id,game_id,status,instance_limit,ends_at,metadata_json "
                    f"FROM service_contracts WHERE id={ph} AND customer_id={ph}",
                    (identifier, customer_id),
                ).fetchone()
                if row is None:
                    raise ValueError("Contrato não encontrado para este cliente.")
                count = session.execute(
                    f"SELECT COUNT(*) AS total FROM instance_contracts WHERE contract_id={ph}",
                    (identifier,),
                ).fetchone()
                used = int(count["total"])
                if action == "delete_contract":
                    if used:
                        raise ValueError("Contrato com instâncias: utilize o fluxo de exclusão com backup e Agent.")
                    session.execute(
                        f"DELETE FROM service_contracts WHERE id={ph} AND customer_id={ph}",
                        (identifier, customer_id),
                    )
                    event = "CUSTOMER_CONTRACT_DELETED"
                    result = {"deleted": True, "id": identifier}
                else:
                    unknown = set(changes) - CONTRACT_FIELDS
                    if unknown:
                        raise ValueError("Campos de contrato não editáveis: " + ", ".join(sorted(unknown)))
                    fields, params = [], []
                    if "instance_limit" in changes:
                        try:
                            limit = int(changes["instance_limit"])
                        except (TypeError, ValueError) as exc:
                            raise ValueError("Limite de instâncias inválido.") from exc
                        if not (max(1, used) <= limit <= 1000):
                            raise ValueError("Limite não pode ser inferior às instâncias já vinculadas.")
                        fields.append(f"instance_limit={ph}")
                        params.append(limit)
                    if "status" in changes:
                        status = str(changes["status"] or "").strip().lower()
                        if status not in CONTRACT_STATUS or status == "deleting":
                            raise ValueError("Status de contrato inválido.")
                        if used and status in {"cancelled", "expired"}:
                            raise ValueError("Há instâncias vinculadas: não encerre o contrato sem o fluxo operacional.")
                        fields.append(f"status={ph}")
                        params.append(status)
                    if "ends_at" in changes:
                        fields.append(f"ends_at={ph}")
                        params.append(_expiry(changes["ends_at"]))
                    if "resource_profile_id" in changes or "product_variant" in changes:
                        metadata = _metadata(row["metadata_json"])
                        if used:
                            raise ValueError("Alterações de perfil/produto exigem migração das instâncias vinculadas.")
                        if "resource_profile_id" in changes:
                            selected = str(changes["resource_profile_id"] or "").strip().lower()
                            profile_id, _, _ = resolve_catalog_resource_profile(
                                root=root, game_id=str(row["game_id"]),
                                requested_profile_id=selected or None,
                                require_catalog=True,
                            )
                            metadata["resource_profile_id"] = profile_id
                            metadata["resource_profile_source"] = "selected" if selected else "game_default"
                        if "product_variant" in changes:
                            product_id = str(changes["product_variant"] or "").strip().lower()
                            products = game_workspace_catalog(root, str(row["game_id"])).get("products") or {}
                            if not isinstance(products, dict) or product_id not in products:
                                raise ValueError("Produto não disponível neste jogo.")
                            product = products[product_id]
                            metadata["product_variant"] = product_id
                            metadata["content_mode"] = product_id
                            metadata["entitlements"] = {
                                str(key): bool(value)
                                for key, value in (product.get("entitlements") or {}).items()
                            }
                        fields.append(f"metadata_json={ph}")
                        params.append(json.dumps(metadata, separators=(",", ":")))
                    if not fields:
                        raise ValueError("Nenhum campo editável informado.")
                    params.extend((identifier, customer_id))
                    session.execute(
                        "UPDATE service_contracts SET " + ", ".join(fields)
                        + f",updated_at={now} WHERE id={ph} AND customer_id={ph}",
                        tuple(params),
                    )
                    event = "CUSTOMER_CONTRACT_UPDATED"
                    result = {"updated": True, "id": identifier, "instances_used": used}
            elif action == "edit_instance":
                unknown = set(changes) - INSTANCE_FIELDS
                if unknown:
                    raise ValueError("Campos de instância não editáveis: " + ", ".join(sorted(unknown)))
                name = str(changes.get("name") or "").strip()
                if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
                    raise ValueError("Nome deve conter entre 1 e 100 caracteres válidos.")
                row = session.execute(
                    f"SELECT status FROM instances WHERE id={ph} AND customer_id={ph}",
                    (identifier, customer_id),
                ).fetchone()
                if row is None or row["status"] == "deleting":
                    raise ValueError("Instância indisponível para edição.")
                session.execute(
                    f"UPDATE instances SET name={ph},updated_at={now} WHERE id={ph} AND customer_id={ph}",
                    (name, identifier, customer_id),
                )
                event = "CUSTOMER_INSTANCE_RENAMED"
                result = {"updated": True, "id": identifier, "name": name}
            else:
                raise ValueError("Ação de edição desconhecida.")
        finally:
            session.close()
    # Audit only successful mutations, after committing the transaction.
    audit_customer_event(
        backend,
        username=str(user.get("username") or ""),
        action=event,
        result="success",
        details={"customer_id": customer_id, "asset_id": identifier,
                 "changed_fields": sorted(changes) if isinstance(changes, dict) else [],
                 "action": action},
    )
    return result


def install_customer_assets_administration(legacy, authenticate):
    previous_post = legacy.DashboardHandler.do_POST

    def post(self):
        if urlparse(self.path).path != PATH:
            return previous_post(self)
        user = authenticate(self.headers)
        if user is None:
            return self.unauthorized()
        try:
            payload = self.read_json_body()
            result = edit_customer_asset(
                payload, user=user,
                backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,
            )
            return self.send_json(200, result)
        except PermissionError as exc:
            return self.send_json(403, {"error": str(exc)})
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        except Exception:
            return self.send_json(500, {"error": "Não foi possível alterar os dados."})

    legacy.DashboardHandler.do_POST = post


__all__ = ["PATH", "edit_customer_asset", "install_customer_assets_administration"]
