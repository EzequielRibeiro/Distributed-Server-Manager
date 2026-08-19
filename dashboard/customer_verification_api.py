#!/usr/bin/env python3
"""Public e-mail verification endpoint."""
from __future__ import annotations
from customer_audit import audit_customer_event
from customer_verification_repository import CustomerVerificationRepository

CUSTOMER_VERIFICATION_PATHS={"/api/customer/email-verification"}

def dispatch_customer_verification(method,path,*,payload,backend):
    if path not in CUSTOMER_VERIFICATION_PATHS:return None
    if method!="POST":return 405,{"error":"method not allowed"}
    try:
        token=str((payload or {}).get("token","")).strip()
        if not token: raise ValueError("verification token is required")
        result=CustomerVerificationRepository(backend).consume(token)
        audit_customer_event(backend,username=result["username"],action="customer.email_verified",details={"customer_id":result["customer_id"]})
        return 200,{"verified":True}
    except ValueError as exc:return 400,{"error":str(exc)}
    except Exception:return 500,{"error":"customer verification operation failed"}
