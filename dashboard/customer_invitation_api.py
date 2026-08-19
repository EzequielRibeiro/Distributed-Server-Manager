#!/usr/bin/env python3
"""Customer team invitation API surface."""
from __future__ import annotations
import os
from customer_account_api import require_customer
from customer_audit import audit_customer_event
from customer_invitation_repository import CustomerInvitationRepository
from customer_mailer import send_invitation
from customer_team_repository import CustomerTeamRepository
from users import hash_password

TEAM_INVITATION_PATHS={
    "/api/customer/team/invitations",
    "/api/customer/team/invitations/create",
    "/api/customer/team/invitations/revoke",
}
PUBLIC_INVITATION_PATHS={"/api/customer/invitations/accept"}

def _owner(user,backend):
    username,customer_id=require_customer(user); role=CustomerTeamRepository(backend).account_role(customer_id,username)
    if role!="owner":raise PermissionError("only the customer owner can manage invitations")
    return username,customer_id

def dispatch_customer_invitations(method,path,*,payload,user,backend):
    if path not in TEAM_INVITATION_PATHS|PUBLIC_INVITATION_PATHS:return None
    body=payload or {}; repo=CustomerInvitationRepository(backend)
    try:
        if path=="/api/customer/invitations/accept":
            if method!="POST":return 405,{"error":"method not allowed"}
            token=str(body.get("token","")).strip(); password=str(body.get("password",""))
            if not token:raise ValueError("invitation token is required")
            result=repo.accept(token,hash_password(password))
            audit_customer_event(backend,username=result["username"],action="customer.invitation_accepted",details={"customer_id":result["customer_id"],"account_role":result["account_role"]})
            return 200,{"accepted":True,"username":result["username"]}
        actor,customer_id=_owner(user,backend)
        if path=="/api/customer/team/invitations":
            if method!="GET":return 405,{"error":"method not allowed"}
            return 200,{"invitations":repo.list(customer_id)}
        if method!="POST":return 405,{"error":"method not allowed"}
        if path.endswith("/create"):
            created=repo.create(customer_id,body.get("email"),body.get("account_role","member"),body.get("instance_access",{}),actor)
            delivered=send_invitation(created["email"],created["token"])
            response={"created":True,"delivered":delivered,"invitation_id":created["id"]}
            if os.environ.get("DSM_CUSTOMER_INVITATION_EXPOSE_TOKEN","").lower() in {"1","true","yes"}:response["invitation_token"]=created["token"]
            audit_customer_event(backend,username=actor,action="customer.invitation_created",details={"customer_id":customer_id,"invitation_id":created["id"],"delivered":delivered})
            return 201,response
        invitation_id=str(body.get("invitation_id","")).strip()
        if not invitation_id:raise ValueError("invitation_id is required")
        repo.revoke(customer_id,invitation_id,actor)
        audit_customer_event(backend,username=actor,action="customer.invitation_revoked",details={"customer_id":customer_id,"invitation_id":invitation_id})
        return 200,{"revoked":True}
    except PermissionError as exc:return 403,{"error":str(exc)}
    except (ValueError,LookupError) as exc:return 400,{"error":str(exc)}
    except Exception:return 500,{"error":"customer invitation operation failed"}
