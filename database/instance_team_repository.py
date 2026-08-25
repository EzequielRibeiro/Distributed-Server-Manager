#!/usr/bin/env python3
"""Instance team identities and exact per-instance permission sets."""
from __future__ import annotations
import re,secrets
from typing import Any
from alert_repository import AlertSession,dialect_for_backend
from customer_identity_repository import insert_customer
from instance_workspace_policy import INSTANCE_PERMISSIONS
from instance_workspace_repository import InstanceWorkspaceRepository
from users import hash_password

class InstanceTeamRepository:
 def __init__(self,backend):self.backend=backend;self.dialect=dialect_for_backend(backend);self.workspace=InstanceWorkspaceRepository(backend)
 def _session(self,c):return AlertSession(self.backend,c)
 @staticmethod
 def _email(value):
  email=str(value or "").strip().lower()
  if not email or "@" not in email or len(email)>320:raise ValueError("valid e-mail is required")
  return email
 @staticmethod
 def _username_seed(email):return (re.sub(r"[^a-z0-9._-]+","-",email.split("@",1)[0].lower()).strip("-._") or "customer")[:48]
 def _allocate_username(self,s,email):
  ph=self.dialect.placeholder;seed=self._username_seed(email)
  for index in range(1000):
   value=seed if index==0 else f"{seed[:42]}-{index}"
   if s.execute(f"SELECT 1 FROM dashboard_users WHERE username={ph}",(value,)).fetchone() is None:return value
  raise RuntimeError("unable to allocate username")
 def _instance_owner_customer(self,s,instance_id):
  ph=self.dialect.placeholder;row=s.execute(f"SELECT customer_id,controller_id FROM instances WHERE id={ph}",(instance_id,)).fetchone()
  if row is None:raise LookupError("instance not found")
  return int(row["customer_id"]),str(row["controller_id"])
 def _require_owner(self,s,instance_id,username):
  customer_id,_=self._instance_owner_customer(s,instance_id);ph=self.dialect.placeholder
  row=s.execute(f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",(customer_id,str(username or "").lower())).fetchone()
  if row is None or str(row["account_role"])!="owner":raise PermissionError("only the Customer owner can manage the instance team")
  return customer_id
 @staticmethod
 def _exact_grants(grants):
  raw=dict(grants or {});invalid=set(raw)-set(INSTANCE_PERMISSIONS)
  if invalid:raise ValueError("unknown permissions: "+", ".join(sorted(invalid)))
  # Persist every permission explicitly. Unchecked means denied.
  result={permission:bool(raw.get(permission,False)) for permission in INSTANCE_PERMISSIONS}
  # Any useful delegated account must at least see the instance.
  if any(value for key,value in result.items() if key!="instance.view"):result["instance.view"]=True
  # Executing commands requires console visibility.
  if result.get("console.execute"):result["console.read"]=True
  return result
 def invite(self,*,instance_id:str,email:str,grants:dict[str,Any],invited_by:str)->dict[str,Any]:
  instance_id=str(instance_id or "").strip();email=self._email(email);exact=self._exact_grants(grants);temporary_password=None;created=False
  self.backend.initialize();ph=self.dialect.placeholder
  with self.backend.transaction() as c:
   s=self._session(c)
   try:
    target_customer_id,controller_id=self._instance_owner_customer(s,instance_id);self._require_owner(s,instance_id,invited_by)
    identity=s.execute(f"SELECT i.username,u.customer_id FROM customer_user_identities i JOIN dashboard_users u ON u.username=i.username WHERE LOWER(i.email)=LOWER({ph})",(email,)).fetchone()
    if identity is None:
     username=self._allocate_username(s,email);temporary_password=secrets.token_urlsafe(12);active=True if self.backend.name=="postgresql" else 1
     own=insert_customer(s,backend_name=self.backend.name,parameters=self.dialect.parameters(8),controller_id=controller_id,name=email,email=email,phone=None,status="active",billing_provider=None,billing_customer_id=None,billing_status="unlinked")
     s.execute(f"UPDATE customers SET account_email={ph},registration_status='incomplete',email_verified_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} WHERE id={ph}",(email,own.id))
     s.execute("INSERT INTO dashboard_users(username,password_hash,role,customer_id,active) "+f"VALUES ({self.dialect.parameters(5)})",(username,hash_password(temporary_password),"customer",own.id,active))
     s.execute("INSERT INTO customer_user_identities(username,email,email_verified_at) "+f"VALUES ({ph},{ph},{self.dialect.current_timestamp})",(username,email))
     s.execute("INSERT INTO customer_password_state(username,must_change_password) "+f"VALUES ({self.dialect.parameters(2)})",(username,active))
     s.execute("INSERT INTO customer_account_members(customer_id,username,account_role) "+f"VALUES ({self.dialect.parameters(3)})",(own.id,username,"owner"));created=True
    else:username=str(identity["username"])
    if s.execute(f"SELECT 1 FROM customer_account_members WHERE customer_id={ph} AND username={ph}",(target_customer_id,username)).fetchone() is None:s.execute("INSERT INTO customer_account_members(customer_id,username,account_role) "+f"VALUES ({self.dialect.parameters(3)})",(target_customer_id,username,"member"))
    access=s.execute(f"SELECT 1 FROM instance_access WHERE username={ph} AND instance_id={ph}",(username,instance_id)).fetchone()
    if access is None:s.execute("INSERT INTO instance_access(username,instance_id,permission_profile) "+f"VALUES ({self.dialect.parameters(3)})",(username,instance_id,"custom"))
    else:s.execute(f"UPDATE instance_access SET permission_profile='custom' WHERE username={ph} AND instance_id={ph}",(username,instance_id))
   finally:s.close()
  self.workspace.set_permission_grants(username,instance_id,exact)
  return {"username":username,"email":email,"created":created,"temporary_password":temporary_password,"must_change_password":created,"grants":exact,"permissions":sorted(self.workspace.effective_permissions_for(username,instance_id))}
 def set_grants(self,*,instance_id,username,grants,changed_by):
  instance_id=str(instance_id or "").strip();username=str(username or "").strip().lower();exact=self._exact_grants(grants);ph=self.dialect.placeholder
  with self.backend.transaction() as c:
   s=self._session(c)
   try:
    self._require_owner(s,instance_id,changed_by)
    row=s.execute(f"SELECT 1 FROM instance_access WHERE username={ph} AND instance_id={ph}",(username,instance_id)).fetchone()
    if row is None:raise LookupError("instance team member not found")
    s.execute(f"UPDATE instance_access SET permission_profile='custom' WHERE username={ph} AND instance_id={ph}",(username,instance_id))
   finally:s.close()
  saved=self.workspace.set_permission_grants(username,instance_id,exact)
  return {"username":username,"grants":saved,"permissions":sorted(self.workspace.effective_permissions_for(username,instance_id))}
 def remove_access(self,*,instance_id,username,removed_by):
  instance_id=str(instance_id or "").strip();username=str(username or "").strip().lower();ph=self.dialect.placeholder
  with self.backend.transaction() as c:
   s=self._session(c)
   try:
    customer_id=self._require_owner(s,instance_id,removed_by)
    own=s.execute(f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",(customer_id,username)).fetchone()
    if own is not None and str(own["account_role"])=="owner":raise PermissionError("instance owner access cannot be removed")
    s.execute(f"DELETE FROM instance_permission_grants WHERE username={ph} AND instance_id={ph}",(username,instance_id));s.execute(f"DELETE FROM instance_access WHERE username={ph} AND instance_id={ph}",(username,instance_id))
    still=s.execute("SELECT 1 FROM instance_access ia JOIN instances i ON i.id=ia.instance_id "+f"WHERE ia.username={ph} AND i.customer_id={ph} LIMIT 1",(username,customer_id)).fetchone()
    if still is None:s.execute(f"DELETE FROM customer_account_members WHERE customer_id={ph} AND username={ph} AND account_role='member'",(customer_id,username))
   finally:s.close()
  return {"removed":True,"username":username,"instance_id":instance_id,"identity_preserved":True}
 def members(self,instance_id):
  context=self.workspace.instance_context(instance_id);customer_id=int(context["customer_id"]);ph=self.dialect.placeholder
  with self.backend.connect() as c:
   s=self._session(c)
   try:rows=s.execute("SELECT m.username,m.account_role,u.active,i.email,ia.permission_profile FROM customer_account_members m JOIN dashboard_users u ON u.username=m.username LEFT JOIN customer_user_identities i ON i.username=m.username JOIN instance_access ia ON ia.username=m.username "+f"WHERE m.customer_id={ph} AND ia.instance_id={ph} ORDER BY m.username",(customer_id,instance_id)).fetchall()
   finally:s.close()
  result=[]
  for row in rows:
   item=dict(row);item["grants"]=self.workspace.permission_grants(str(row["username"]),instance_id);item["permissions"]=sorted(self.workspace.effective_permissions_for(str(row["username"]),instance_id));result.append(item)
  return result
 def shared_instances(self,username):
  username=str(username or "").strip().lower();ph=self.dialect.placeholder
  with self.backend.connect() as c:
   s=self._session(c)
   try:rows=s.execute("SELECT i.id,i.name,i.game_id,i.runtime_id,i.status,i.agent_id,i.customer_id,ia.permission_profile FROM instance_access ia JOIN instances i ON i.id=ia.instance_id JOIN dashboard_users u ON u.username=ia.username "+f"WHERE ia.username={ph} AND (u.customer_id IS NULL OR i.customer_id<>u.customer_id) ORDER BY i.name,i.id",(username,)).fetchall()
   finally:s.close()
  result=[]
  for row in rows:
   item=dict(row);item["permissions"]=sorted(self.workspace.effective_permissions_for(username,str(row["id"])));result.append(item)
  return result

__all__=["InstanceTeamRepository"]
