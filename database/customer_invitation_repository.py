#!/usr/bin/env python3
"""Customer team invitations and selected per-instance grants."""
from __future__ import annotations
import hashlib,re,secrets,uuid
from datetime import datetime,timedelta,timezone
from alert_repository import AlertSession,dialect_for_backend
from customer_identity import normalize_email,sftp_username_seed

ROLES={"manager","member"}; PROFILES={"viewer","operator","manager"}
def _digest(token): return hashlib.sha256(token.encode()).hexdigest()
def _db_datetime(backend,value):
    if backend.name=="mysql": return value.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    if backend.name=="postgresql": return value
    return value.astimezone(timezone.utc).isoformat()
def _parse(value):
    if isinstance(value,datetime): dt=value
    else: dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

class CustomerInvitationRepository:
    def __init__(self,backend): self.backend=backend; self.dialect=dialect_for_backend(backend)
    def _session(self,c): return AlertSession(self.backend,c)
    def list(self,customer_id):
        self.backend.initialize(); ph=self.dialect.placeholder
        with self.backend.connect() as c:
            s=self._session(c)
            try:
                rows=s.execute("SELECT id,email,account_role,expires_at,accepted_at,revoked_at,invited_by,created_at FROM customer_invitations "
                               f"WHERE customer_id={ph} ORDER BY created_at DESC",(customer_id,)).fetchall()
                result=[]
                for row in rows:
                    item=dict(row); grants=s.execute("SELECT instance_id,permission_profile FROM customer_invitation_access "+f"WHERE invitation_id={ph} ORDER BY instance_id",(row["id"],)).fetchall(); item["instance_access"]={str(g["instance_id"]):str(g["permission_profile"]) for g in grants}; result.append(item)
                return result
            finally:s.close()
    def create(self,customer_id,email,account_role,instance_access,invited_by,*,ttl_hours=72):
        email=normalize_email(email); account_role=str(account_role).lower()
        if account_role not in ROLES: raise ValueError("invalid delegated account role")
        if not isinstance(instance_access,dict): raise ValueError("instance_access must be an object")
        self.backend.initialize(); ph=self.dialect.placeholder; token=secrets.token_urlsafe(32); invitation_id=str(uuid.uuid4())
        expires=datetime.now(timezone.utc)+timedelta(hours=max(1,min(int(ttl_hours),168)))
        with self.backend.transaction() as c:
            s=self._session(c)
            try:
                actor=s.execute(f"SELECT 1 FROM customer_account_members WHERE customer_id={ph} AND username={ph} AND account_role='owner'",(customer_id,invited_by)).fetchone()
                if actor is None: raise PermissionError("only the customer owner can invite users")
                duplicate=s.execute("SELECT 1 FROM customer_user_identities i JOIN dashboard_users u ON u.username=i.username "+f"WHERE LOWER(i.email)=LOWER({ph})",(email,)).fetchone()
                if duplicate is not None: raise ValueError("invitation could not be created")
                s.execute("INSERT INTO customer_invitations(id,customer_id,email,account_role,token_hash,expires_at,invited_by) "+f"VALUES ({self.dialect.parameters(7)})",(invitation_id,customer_id,email,account_role,_digest(token),_db_datetime(self.backend,expires),invited_by))
                for instance_id,profile in instance_access.items():
                    profile=str(profile).lower()
                    if profile not in PROFILES: raise ValueError("invalid instance permission profile")
                    exists=s.execute(f"SELECT 1 FROM instances WHERE id={ph} AND customer_id={ph}",(str(instance_id),customer_id)).fetchone()
                    if exists is None: raise PermissionError("instance is outside customer scope")
                    s.execute("INSERT INTO customer_invitation_access(invitation_id,instance_id,permission_profile) "+f"VALUES ({self.dialect.parameters(3)})",(invitation_id,str(instance_id),profile))
            finally:s.close()
        return {"id":invitation_id,"token":token,"email":email,"expires_at":expires.isoformat()}
    def revoke(self,customer_id,invitation_id,actor):
        self.backend.initialize(); ph=self.dialect.placeholder
        with self.backend.transaction() as c:
            s=self._session(c)
            try:
                owner=s.execute(f"SELECT 1 FROM customer_account_members WHERE customer_id={ph} AND username={ph} AND account_role='owner'",(customer_id,actor)).fetchone()
                if owner is None: raise PermissionError("only the customer owner can revoke invitations")
                row=s.execute(f"SELECT accepted_at,revoked_at FROM customer_invitations WHERE id={ph} AND customer_id={ph}",(invitation_id,customer_id)).fetchone()
                if row is None: raise LookupError("invitation not found")
                if row["accepted_at"]: raise ValueError("accepted invitation cannot be revoked")
                if not row["revoked_at"]: s.execute(f"UPDATE customer_invitations SET revoked_at={self.dialect.current_timestamp} WHERE id={ph}",(invitation_id,))
            finally:s.close()
    def _allocate_username(self,s,email):
        ph=self.dialect.placeholder; seed=sftp_username_seed(email)
        for attempt in range(101):
            candidate=seed if attempt==0 else f"{seed[:22].rstrip('-._')}-{hashlib.sha256((email+str(attempt)).encode()).hexdigest()[:8]}"
            if s.execute(f"SELECT 1 FROM dashboard_users WHERE username={ph}",(candidate,)).fetchone() is None:return candidate
        raise RuntimeError("unable to allocate customer username")
    def accept(self,token,password_hash):
        self.backend.initialize(); ph=self.dialect.placeholder; now=datetime.now(timezone.utc)
        with self.backend.transaction() as c:
            s=self._session(c)
            try:
                row=s.execute("SELECT ci.id,ci.customer_id,ci.email,ci.account_role,ci.expires_at,ci.accepted_at,ci.revoked_at FROM customer_invitations ci JOIN customers c ON c.id=ci.customer_id "+f"WHERE ci.token_hash={ph} AND c.status='active'",(_digest(token),)).fetchone()
                if row is None or row["accepted_at"] or row["revoked_at"]: raise ValueError("invalid invitation token")
                if _parse(row["expires_at"])<=now: raise ValueError("expired invitation token")
                username=self._allocate_username(s,str(row["email"])); customer_id=str(row["customer_id"])
                s.execute("INSERT INTO dashboard_users(username,password_hash,role,scope_id,active) "+f"VALUES ({self.dialect.parameters(4)},TRUE)",(username,password_hash,"customer",customer_id))
                s.execute("INSERT INTO customer_user_identities(username,email,email_verified_at) "+f"VALUES ({ph},{ph},{self.dialect.current_timestamp})",(username,str(row["email"])))
                s.execute("INSERT INTO customer_account_members(customer_id,username,account_role) "+f"VALUES ({self.dialect.parameters(3)})",(customer_id,username,str(row["account_role"])))
                grants=s.execute("SELECT instance_id,permission_profile FROM customer_invitation_access "+f"WHERE invitation_id={ph}",(row["id"],)).fetchall()
                for grant in grants:
                    s.execute("INSERT INTO instance_access(username,instance_id,permission_profile) "+f"VALUES ({self.dialect.parameters(3)})",(username,str(grant["instance_id"]),str(grant["permission_profile"])))
                s.execute(f"UPDATE customer_invitations SET accepted_at={self.dialect.current_timestamp} WHERE id={ph}",(row["id"],))
                return {"username":username,"customer_id":customer_id,"account_role":str(row["account_role"])}
            finally:s.close()
