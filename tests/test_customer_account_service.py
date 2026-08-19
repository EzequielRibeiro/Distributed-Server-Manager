#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dashboard'))
sys.path.insert(0,str(ROOT/'database'))
from customer_account_service import may_manage_members, normalize_registration, permissions_for
from customer_account_api import registration_payload
from customer_identity import normalize_email

def test_owner_may_manage_members():
    assert may_manage_members('owner') is True
    assert may_manage_members('manager') is False
    assert may_manage_members('member') is False

def test_roles_have_expected_instance_scope():
    assert 'instance.create' in permissions_for('owner')
    assert 'instance.create' in permissions_for('manager')
    assert 'instance.create' not in permissions_for('member')

def test_registration_normalization():
    request=normalize_registration({'name':'Cliente Exemplo','email':' USER@Example.COM ','document_type':'cpf'})
    assert request.name=='Cliente Exemplo'
    assert request.email=='user@example.com'

def test_registration_requires_password():
    try:
        registration_payload({'name':'Cliente','email':'user@example.com','password':'short'},normalize_email)
    except ValueError:
        pass
    else:
        raise AssertionError('short password must be rejected')
