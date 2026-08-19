#!/usr/bin/env python3
"""Transport-neutral HTTP contract for instance lifecycle operations."""
from pathlib import Path

DELETE_PATH="/api/instance/delete"
REINSTALL_PATH="/api/instance/reinstall/v2"

def _identity(payload):
    return (str(payload.get("server") or ""),str(payload.get("game") or ""),str(payload.get("instance") or ""))

def _require(server,game,instance_id):
    if not server or not game or not instance_id:
        raise ValueError("server, game and instance are required")

def dispatch_instance_lifecycle_post(path,payload,*,user,root,resolve_instance,has_permission,
    begin_deletion,stop_instance,delete_record,audit,reinstall_busy=None):
    if path != DELETE_PATH:
        return None
    server,game,instance_id=_identity(payload)
    _require(server,game,instance_id)
    instance_path=Path(resolve_instance(server,game,instance_id))
    if not has_permission(user,instance_path,"instance.delete"):
        raise PermissionError("Usuário sem permissão para excluir esta instância.")
    if reinstall_busy is not None and reinstall_busy(instance_id):
        return 409,{"error":"Reinstalação em andamento; a exclusão está bloqueada.","busy":True,"instance_id":instance_id}
    if str(payload.get("confirmation", "")) != instance_path.name:
        raise ValueError("instance identifier confirmation does not match")
    status,operation=begin_deletion(
        root,instance_path,server=server,game=game,
        final_backup=payload.get("final_backup") is True,
        stop_instance=stop_instance,delete_record=delete_record,audit=audit,
    )
    return status,operation

def dispatch_instance_reinstall_post(path,payload,*,user,resolve_instance,can_access,reinstall_busy,
    reinstall_instance,runner,deletion_status=None,root=None):
    if path != REINSTALL_PATH:
        return None
    server,game,instance_id=_identity(payload)
    _require(server,game,instance_id)
    instance_path=Path(resolve_instance(server,game,instance_id))
    if not can_access(user,instance_path,write=True):
        raise PermissionError("Usuário sem permissão para reinstalar esta instância.")
    deletion_active=False
    if deletion_status is not None and root is not None:
        operation=deletion_status(root,instance_id)
        deletion_active=bool(isinstance(operation,dict) and operation.get("active"))
    if deletion_active or reinstall_busy(instance_id):
        return 409,{"error":"Já existe uma operação incompatível em andamento para esta instância.","busy":True,"instance_id":instance_id}
    result=reinstall_instance(
        instance_path,
        preserve_config=payload.get("preserve_config",True) is True,
        preserve_map=payload.get("preserve_map",True) is True,
        runner=runner,
    )
    return 200,result
