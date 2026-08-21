#!/usr/bin/env python3
"""Administrative HTTP surface for E2 HA/DR."""
from __future__ import annotations
from typing import Any
from ha_dr_repository import HADisasterRecoveryRepository

HA_DR_PATH='/api/ha'

def _admin(user:dict[str,Any]|None)->bool:
    return bool(user and str(user.get('role') or '').lower() in {'admin','controller'})

def dispatch_ha_get(path:str,query:dict[str,list[str]],*,user,backend):
    if path!=HA_DR_PATH:return None
    if not _admin(user):return 403,{'error':'forbidden'}
    cluster=(query.get('cluster') or [None])[0]
    if not cluster:return 400,{'error':'cluster is required'}
    try:
        r=HADisasterRecoveryRepository(backend);r.initialize();return 200,r.cluster_status(cluster)
    except ValueError as exc:return 404,{'error':str(exc)}
    except Exception:return 500,{'error':'failed to read HA status'}

def dispatch_ha_post(path:str,payload:dict[str,Any]|None,*,user,backend):
    if path!=HA_DR_PATH:return None
    if not _admin(user):return 403,{'error':'forbidden'}
    body=dict(payload or {}); action=str(body.pop('action','')).strip().lower()
    try:
        r=HADisasterRecoveryRepository(backend);r.initialize()
        if action=='cluster_set':out=r.put_cluster(body)
        elif action=='member_set':out=r.put_member(body)
        elif action=='recovery_point_create':out=r.create_recovery_point(body['cluster_id'],source_controller_id=body['source_controller_id'],kind=body.get('kind','control_plane'),location=body['location'],checksum=body.get('checksum'),metadata=body.get('metadata'))
        elif action=='failover_request':out=r.request_failover(body['cluster_id'],target_controller_id=body.get('target_controller_id'),reason=body.get('reason','manual'),requested_by=str(user.get('username') or user.get('id') or 'dashboard'),automatic=bool(body.get('automatic',False)))
        elif action=='failover_transition':out=r.transition_failover(body['operation_id'],body['state'],message=body.get('message'))
        else:return 400,{'error':'unsupported HA action'}
        return 200,out
    except KeyError as exc:return 400,{'error':f'missing field: {exc.args[0]}'}
    except (ValueError,RuntimeError) as exc:return 409,{'error':str(exc)}
    except Exception:return 500,{'error':'HA operation failed'}

__all__=['HA_DR_PATH','dispatch_ha_get','dispatch_ha_post']
