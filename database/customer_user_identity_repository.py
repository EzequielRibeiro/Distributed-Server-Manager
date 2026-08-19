#!/usr/bin/env python3
"""Per-login customer e-mail identity persistence."""
from __future__ import annotations
from typing import Any
from alert_repository import AlertSession,dialect_for_backend

class CustomerUserIdentityRepository:
    def __init__(self, backend):
        self.backend=backend; self.dialect=dialect_for_backend(backend)
    def _session(self, connection): return AlertSession(self.backend, connection)
    def set_identity(self, username:str, email:str, *, verified:bool=False, connection:Any|None=None)->None:
        ph=self.dialect.placeholder
        def work(conn):
            session=self._session(conn)
            try:
                row=session.execute(f"SELECT username FROM customer_user_identities WHERE username={ph}",(username,)).fetchone()
                verified_sql=self.dialect.current_timestamp if verified else "NULL"
                if row is None:
                    session.execute("INSERT INTO customer_user_identities(username,email,email_verified_at) "
                                    f"VALUES ({ph},{ph},{verified_sql})",(username,email))
                else:
                    session.execute(f"UPDATE customer_user_identities SET email={ph},email_verified_at={verified_sql} WHERE username={ph}",(email,username))
            finally: session.close()
        if connection is not None: work(connection); return
        self.backend.initialize()
        with self.backend.transaction() as conn: work(conn)
    def username_for_email(self,email:str)->str|None:
        self.backend.initialize(); ph=self.dialect.placeholder
        with self.backend.connect() as connection:
            session=self._session(connection)
            try:
                row=session.execute(f"SELECT username FROM customer_user_identities WHERE LOWER(email)=LOWER({ph})",(email,)).fetchone()
                return None if row is None else str(row["username"])
            finally: session.close()
