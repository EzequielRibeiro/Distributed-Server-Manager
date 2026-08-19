#!/usr/bin/env python3
"""One-time customer e-mail verification tokens."""
from __future__ import annotations
import hashlib,secrets,uuid
from datetime import datetime,timedelta,timezone
from alert_repository import AlertSession,dialect_for_backend

def _digest(token:str)->str:return hashlib.sha256(token.encode()).hexdigest()
def _db_datetime(backend, value:datetime):
    if backend.name=="mysql": return value.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    if backend.name=="postgresql": return value
    return value.astimezone(timezone.utc).isoformat()
def _parse(value)->datetime:
    if isinstance(value,datetime): dt=value
    else: dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

class CustomerVerificationRepository:
    def __init__(self,backend): self.backend=backend; self.dialect=dialect_for_backend(backend)
    def create(self,username:str,*,ttl_minutes:int=60*24)->str:
        self.backend.initialize(); token=secrets.token_urlsafe(32); digest=_digest(token); ph=self.dialect.placeholder
        expires=datetime.now(timezone.utc)+timedelta(minutes=max(10,min(int(ttl_minutes),10080)))
        with self.backend.transaction() as connection:
            s=AlertSession(self.backend,connection)
            try:
                s.execute(f"DELETE FROM customer_email_verification WHERE username={ph} AND consumed_at IS NULL",(username,))
                s.execute("INSERT INTO customer_email_verification(id,username,token_hash,expires_at) "
                          f"VALUES ({self.dialect.parameters(4)})",(str(uuid.uuid4()),username,digest,_db_datetime(self.backend,expires)))
            finally:s.close()
        return token
    def consume(self,token:str)->dict:
        self.backend.initialize(); ph=self.dialect.placeholder; digest=_digest(token); now=datetime.now(timezone.utc)
        with self.backend.transaction() as connection:
            s=AlertSession(self.backend,connection)
            try:
                row=s.execute("SELECT v.id,v.username,v.expires_at,v.consumed_at,u.scope_id,i.email "
                              "FROM customer_email_verification v JOIN dashboard_users u ON u.username=v.username "
                              "JOIN customer_user_identities i ON i.username=v.username "
                              f"WHERE v.token_hash={ph}",(digest,)).fetchone()
                if row is None or row["consumed_at"]: raise ValueError("invalid verification token")
                if _parse(row["expires_at"])<=now: raise ValueError("expired verification token")
                username=str(row["username"]); customer_id=str(row["scope_id"])
                s.execute(f"UPDATE customer_email_verification SET consumed_at={self.dialect.current_timestamp} WHERE id={ph}",(row["id"],))
                s.execute(f"UPDATE customer_user_identities SET email_verified_at={self.dialect.current_timestamp} WHERE username={ph}",(username,))
                s.execute(f"UPDATE dashboard_users SET active=TRUE,updated_at={self.dialect.current_timestamp} WHERE username={ph}",(username,))
                s.execute(f"UPDATE customers SET registration_status='active',email_verified_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} WHERE id={ph}",(customer_id,))
                return {"username":username,"customer_id":customer_id,"email":str(row["email"])}
            finally:s.close()
