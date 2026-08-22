#!/usr/bin/env python3
"""Dedicated customer team and per-instance permission API surface."""
from __future__ import annotations
import re
from customer_account_api import member_capabilities,require_customer,require_member_management
from customer_audit import audit_customer_event
from customer_user_repository import CustomerUserRepository
from users import hash_password
CUSTOMER_TEAM_PATHS={"/api/customer/team","/api/customer/team/members/create","/api/customer/team/members/role","/api/customer/team/members/remove","/api/customer/team/access"}
_USERNAME_RE=re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")
def _actor(repository,user):
    username,customer_id=require_customer(user); account_role=repository.require_membership(customer_id,username)
    return username,customer_id,account_role
def _snapshot(repository,customer_id,actor_role):return {"members":repository.list_members(customer_id),"instances":repository.list_instances(customer_id),"capabilities":member_capabilities(actor_role),"rbac":{"account_roles":["owner","manager","member"],"delegable_account_roles":["manager","member"],"instance_profiles":["viewer","operator","manager"],"account_role_is_not_instance_profile":True,"owner_manages_team":True,"scope_is_session_bound":True,"last_owner_protected":True}}
def _target(body):
    username=str(body.get("username","")).strip().lower()
    if not _USERNAME_RE.fullmatch(username):raise ValueError("invalid username")
    return username
def dispatch_customer_team(method,path,*,payload,user,backend):
    if path not in CUSTOMER_TEAM_PATHS:return None
    repository=CustomerUserRepository(backend); body=payload or {}
    try:
        actor,customer_id,actor_role=_actor(repository,user)
        if path=="/api/customer/team":
            if method!="GET":return 405,{"error":"method not allowed"}
            return 200,_snapshot(repository,customer_id,actor_role)
        if method!="POST":return 405,{"error":"method not allowed"}
        require_member_management(actor_role); target=_target(body)
        if path=="/api/customer/team/members/create":
            password=str(body.get("password",""))
            if len(password)<8:raise ValueError("password must have at least 8 characters")
            role=str(body.get("account_role","member")).strip().lower(); repository.create_member(customer_id,target,hash_password(password),role); audit_customer_event(backend,username=actor,action="customer.member_created",details={"target":target,"account_role":role})
        elif path=="/api/customer/team/members/role":
            role=str(body.get("account_role","member")).strip().lower(); repository.set_account_role(customer_id,target,role); audit_customer_event(backend,username=actor,action="customer.member_role_changed",details={"target":target,"account_role":role})
        elif path=="/api/customer/team/members/remove":
            if repository.account_role(customer_id,target)=="owner" and repository.owner_count(customer_id)<=1:raise PermissionError("the last customer owner cannot be removed")
            repository.remove_member(customer_id,target); audit_customer_event(backend,username=actor,action="customer.member_removed",details={"target":target})
        elif path=="/api/customer/team/access":
            instance_id=str(body.get("instance_id","")).strip()
            if not instance_id:raise ValueError("instance_id is required")
            repository.require_instance(customer_id,instance_id)
            profile=str(body.get("permission_profile","")).strip().lower() or None; repository.set_instance_access(customer_id,target,instance_id,profile); audit_customer_event(backend,username=actor,action="customer.instance_access_changed",instance_id=instance_id,details={"target":target,"permission_profile":profile})
        return 200,_snapshot(repository,customer_id,actor_role)
    except PermissionError as exc:return 403,{"error":str(exc)}
    except (ValueError,LookupError) as exc:return 400,{"error":str(exc)}
    except Exception:return 500,{"error":"customer team operation failed"}
