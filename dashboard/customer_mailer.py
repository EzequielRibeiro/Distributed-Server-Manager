#!/usr/bin/env python3
"""SMTP delivery for customer onboarding, verification and invitations."""
from __future__ import annotations
import os,smtplib,ssl
from email.message import EmailMessage
from urllib.parse import urlencode

def _settings():
    host=os.environ.get("DSM_SMTP_HOST","").strip(); sender=os.environ.get("DSM_SMTP_FROM","").strip(); base=os.environ.get("DSM_PUBLIC_BASE_URL","").strip().rstrip("/")
    if not host or not sender or not base:return None
    return {"host":host,"port":int(os.environ.get("DSM_SMTP_PORT","587")),"sender":sender,"base":base,"user":os.environ.get("DSM_SMTP_USER","").strip(),"password":os.environ.get("DSM_SMTP_PASSWORD",""),"tls":os.environ.get("DSM_SMTP_STARTTLS","1").lower() not in {"0","false","no"}}
def _send(to,subject,text):
    cfg=_settings()
    if cfg is None:return False
    msg=EmailMessage(); msg["From"]=cfg["sender"]; msg["To"]=to; msg["Subject"]=subject; msg.set_content(text)
    with smtplib.SMTP(cfg["host"],cfg["port"],timeout=20) as smtp:
        if cfg["tls"]: smtp.starttls(context=ssl.create_default_context())
        if cfg["user"]: smtp.login(cfg["user"],cfg["password"])
        smtp.send_message(msg)
    return True
def send_verification(email,token):
    cfg=_settings(); base=(cfg or {}).get("base",os.environ.get("DSM_PUBLIC_BASE_URL","").rstrip("/")); link=f"{base}/customer-verify-email.html?{urlencode({'token':token})}" if base else ""
    return _send(email,"Verifique seu e-mail — Capivara DSM",f"Confirme seu cadastro no Capivara DSM:\n\n{link}\n")
def send_invitation(email,token):
    cfg=_settings(); base=(cfg or {}).get("base",os.environ.get("DSM_PUBLIC_BASE_URL","").rstrip("/")); link=f"{base}/customer-invitation.html?{urlencode({'token':token})}" if base else ""
    return _send(email,"Convite para equipe — Capivara DSM",f"Você foi convidado para uma equipe no Capivara DSM:\n\n{link}\n")
def send_temporary_password(email,username,password,*,reset=False):
    cfg=_settings(); base=(cfg or {}).get("base",os.environ.get("DSM_PUBLIC_BASE_URL","").rstrip("/")); link=f"{base}/customer-login.html" if base else ""
    subject="Nova senha provisória — Capivara DSM" if reset else "Acesso ao Capivara DSM"
    action="Sua senha foi redefinida pelo administrador." if reset else "Seu acesso ao Capivara DSM foi criado."
    text=(f"{action}\n\nLogin: {username}\nSenha provisória: {password}\n\n"
          "No primeiro acesso você deverá criar uma nova senha.\n"
          + (f"\nAcesse: {link}\n" if link else ""))
    return _send(email,subject,text)
