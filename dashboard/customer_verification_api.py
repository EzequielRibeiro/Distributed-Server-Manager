#!/usr/bin/env python3
"""Public e-mail verification and resend endpoints."""
from __future__ import annotations
import os
from alert_repository import AlertSession,dialect_for_backend
from customer_audit import audit_customer_event
from customer_identity import normalize_email
from customer_mailer import send_verification
from customer_verification_repository import CustomerVerificationRepository

CUSTOMER_VERIFICATION_PATHS={"/api/customer/email-verification","/api/customer/email-verification/resend"}

def _resend(payload,backend):
    result={"accepted":True}
    try: email=normalize_email((payload or {}).get("email"))
    except ValueError: return result
    backend.initialize(); ph=dialect_for_backend(backend).placeholder
    with backend.connect() as connection:
        s=AlertSession(backend,connection)
        try:
            row=s.execute("SELECT u.username,i.email FROM customer_user_identities i JOIN dashboard_users u ON u.username=i.username JOIN customers c ON c.id=u.scope_id "
                          f"WHERE LOWER(i.email)=LOWER({ph}) AND u.role='customer' AND u.active=FALSE AND c.registration_status='pending' ORDER BY u.username LIMIT 1",(email,)).fetchone()
        finally:s.close()
    if row is not None:
        username=str(row["username"]); token=CustomerVerificationRepository(backend).create(username); delivered=send_verification(str(row["email"]),token)
        audit_customer_event(backend,username=username,action="customer.email_verification_resent",details={"delivered":delivered})
        if os.environ.get("DSM_CUSTOMER_VERIFICATION_EXPOSE_TOKEN","").lower() in {"1","true","yes"}: result["verification_token"]=token
    return result

def dispatch_customer_verification(method,path,*,payload,backend):
    if path not in CUSTOMER_VERIFICATION_PATHS:return None
    if method!="POST":return 405,{"error":"method not allowed"}
    try:
        if path.endswith("/resend"):
            return 202,_resend(payload,backend)
        token=str((payload or {}).get("token","")).strip()
        if not token: raise ValueError("verification token is required")
        result=CustomerVerificationRepository(backend).consume(token)
        audit_customer_event(backend,username=result["username"],action="customer.email_verified",details={"customer_id":result["customer_id"]})
        return 200,{"verified":True}
    except ValueError as exc:return 400,{"error":str(exc)}
    except Exception:return 500,{"error":"customer verification operation failed"}
