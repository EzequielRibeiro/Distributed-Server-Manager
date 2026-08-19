#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dashboard'));sys.path.insert(0,str(ROOT/'database'))
from customer_account_service import permissions_for
from customer_team_repository import DELEGABLE_ACCOUNT_ROLES, INSTANCE_PROFILES


def test_account_roles_do_not_replace_instance_profiles():
    assert DELEGABLE_ACCOUNT_ROLES == {'manager','member'}
    assert INSTANCE_PROFILES == {'viewer','operator','manager'}
    assert 'account.members.manage' not in permissions_for('manager')
    assert 'account.members.manage' in permissions_for('owner')


def test_member_cannot_create_instance():
    assert 'instance.create' not in permissions_for('member')


def test_account_manager_can_create_but_not_manage_team():
    assert 'instance.create' in permissions_for('manager')
    assert 'account.members.manage' not in permissions_for('manager')
