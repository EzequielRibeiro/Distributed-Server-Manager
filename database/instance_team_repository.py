#!/usr/bin/env python3
"""Invite people to an instance without making identity equal ownership.

A new e-mail receives its own Customer account (registration incomplete) and is
also linked to the inviting Customer through ``customer_account_members``. This
means the person can later buy contracts of their own while continuing to
manage shared instances. Existing Customer identities are simply linked.
"""
from __future__ import annotations

import re
import secrets
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from customer_identity_repository import insert_customer
from customer_management_repository import CustomerManagementRepository
from instance_workspace_policy import INSTANCE_PERMISSIONS
from instance_workspace_repository import InstanceWorkspaceRepository
from users import hash_password


class InstanceTeamRepository:
    def __init__(self, backend):
        self.backend=backend;self.dialect=dialect_for_backend(backend);self.workspace=InstanceWorkspaceRepository(backend)
    def _session(self,c):return AlertSession(self.backend,c)
    @staticmethod
    def _email(value):
        email=str(value or "").strip().lower()
        if not email or "@" not in email or len(email)>320:raise ValueError("valid e-mail is required")
        return email
    @staticmethod
    def _username_seed(email):
        seed=re.sub(r"[^a-z0-9._-]+","-",email.split("@",1)[0].lower()).strip("-._") or "customer"
        return seed[:48]
    def _allocate_username(self,s,email):
        ph=self.dialect.placeholder;seed=self._username_seed(email)
        for index in range(1000):
            value=seed if index==0 else f"{seed[:42]}-{index}"
            if s.execute(f"SELECT 1 FROM dashboard_users WHERE username={ph}",(value,)).fetchone() is None:return value
        raise RuntimeError("unable to allocate username")
    def _instance_owner_customer(self,s,instance_id):
        ph=self.dialect.placeholder
        row=s.execute("SELECT i.customer_id,i.controller_id FROM instances i "+f"WHERE i.id={ph}",(instance_id,)).fetchone()
        if row is None:raise LookupError("instance not found")
        return int(row["customer_id"]),str(row["controller_id"])
    def invite(self,*,instance_id:str,email:str,grants:dict[str,Any],invited_by:str)->dict[str,Any]:
        instance_id=str(instance_id or "").strip();email=self._email(email);grants=dict(grants or {})
        invalid=set(grants)-set(INSTANCE_PERMISSIONS)
        if invalid:raise ValueError("unknown permissions: "+", ".join(sorted(invalid)))
        temporary_password=None;created=False
        self.backend.initialize();ph=self.dialect.placeholder
        with self.backend.transaction() as c:
            s=self._session(c)
            try:
                target_customer_id,controller_id=self._instance_owner_customer(s,instance_id)
                actor=s.execute(f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",(target_customer_id,str(invited_by).lower())).fetchone()
                if actor is None or str(actor["account_role"])!="owner":raise PermissionError("only the Customer owner can manage the instance team")
                identity=s.execute(f"SELECT i.username,u.customer_id FROM customer_user_identities i JOIN dashboard_users u ON u.username=i.username WHERE LOWER(i.email)=LOWER({ph})",(email,)).fetchone()
                if identity is None:
                    username=self._allocate_username(s,email);temporary_password=secrets.token_urlsafe(12);active=True if self.backend.name=="postgresql" else 1
                    own=insert_customer(s,backend_name=self.backend.name,parameters=self.dialect.parameters(8),controller_id=controller_id,name=email,email=email,phone=None,status="active",billing_provider=None,billing_customer_id=None,billing_status="unlinked")
                    s.execute(f"UPDATE customers SET account_email={ph},registration_status='incomplete',email_verified_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} WHERE id={ph}",(email,own.id))
                    s.execute("INSERT INTO dashboard_users(username,password_hash,role,customer_id,active) "+f"VALUES ({self.dialect.parameters(5)})",(username,hash_password(temporary_password),"customer",own.id,active))
                    s.execute("INSERT INTO customer_user_identities(username,email,email_verified_at) "+f"VALUES ({ph},{ph},{self.dialect.current_timestamp})",(username,email))
                    s.execute("INSERT INTO customer_password_state(username,must_change_password) "+f"VALUES ({self.dialect.parameters(2)})",(username,active))
                    # Own account permits future contract acquisition independently.
                    s.execute("INSERT INTO customer_account_members(customer_id,username,account_role) "+f"VALUES ({self.dialect.parameters(3)})",(own.id,username,"owner"));created=True
                else:username=str(identity["username"])
                member=s.execute(f"SELECT 1 FROM customer_account_members WHERE customer_id={ph} AND username={ph}",(target_customer_id,username)).fetchone()
                if member is None:s.execute("INSERT INTO customer_account_members(customer_id,username,account_role) "+f"VALUES ({self.dialect.parameters(3)})",(target_customer_id,username,"member"))
                access=s.execute(f"SELECT 1 FROM instance_access WHERE username={ph} AND instance_id={ph}",(username,instance_id)).fetchone()
                if access is None:s.execute("INSERT INTO instance_access(username,instance_id,permission_profile) "+f"VALUES ({self.dialect.parameters(3)})",(username,instance_id,"viewer"))
            finally:s.close()
        # Explicit grants are written after identity/membership transaction.
        self.workspace.set_permission_grants(username,instance_id,{key:bool(value) for key,value in grants.items()})
        return {"username":username,"email":email,"created":created,"temporary_password":temporary_password,"must_change_password":created,"permissions":sorted(self.workspace.effective_permissions_for(username,instance_id))}
    def members(self,instance_id:str)->list[dict[str,Any]]:
        context=self.workspace.instance_context(instance_id);customer_id=int(context["customer_id"]);ph=self.dialect.placeholder
        with self.backend.connect() as c:
            s=self._session(c)
            try:
                rows=s.execute("SELECT m.username,m.account_role,u.active,i.email FROM customer_account_members m JOIN dashboard_users u ON u.username=m.username LEFT JOIN customer_user_identities i ON i.username=m.username JOIN instance_access ia ON ia.username=m.username "+f"WHERE m.customer_id={ph} AND ia.instance_id={ph} ORDER BY m.username",(customer_id,instance_id)).fetchall()
            finally:s.close()
        result=[]
        for row in rows:
            item=dict(row);item["grants"]=self.workspace.permission_grants(str(row["username"]),instance_id);item["permissions"]=sorted(self.workspace.effective_permissions_for(str(row["username"]),instance_id));result.append(item)
        return result


__all__=["InstanceTeamRepository"]
