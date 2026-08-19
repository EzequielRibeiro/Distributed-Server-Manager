#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dashboard'));sys.path.insert(0,str(ROOT/'database'))
from customer_account_http import dispatch_customer_account

def test_unknown_path_is_not_claimed():
    assert dispatch_customer_account('GET','/api/other',payload=None,user=None,backend=None) is None

def test_customer_members_requires_authentication():
    status,body=dispatch_customer_account('GET','/api/customer/members',payload=None,user=None,backend=None)
    assert status==403
    assert 'error' in body

def test_public_endpoint_rejects_wrong_method_without_backend():
    status,body=dispatch_customer_account('GET','/api/customer/register',payload=None,user=None,backend=None)
    assert status==405
    assert body['error']=='method not allowed'
