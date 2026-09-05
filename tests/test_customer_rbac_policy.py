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


def test_customer_rbac_preserves_internal_numeric_scope_id():
    import customer_rbac
    from unittest.mock import patch

    calls = []

    class FakeRepository:
        def __init__(self, backend):
            self.backend = backend

        def require_instance(self, customer_reference, instance_id):
            calls.append(("require", customer_reference, instance_id))
            return {"id": instance_id}

        def permission_profile(self, customer_reference, username, instance_id):
            calls.append(
                ("profile", customer_reference, username, instance_id)
            )
            return "manager"

        def account_role(self, customer_reference, username):
            calls.append(("role", customer_reference, username))
            return "owner"

    user = {
        "role": "customer",
        "scope_id": 1,
        "username": "aurora",
    }

    with patch.object(
        customer_rbac,
        "CustomerUserRepository",
        FakeRepository,
    ):
        assert customer_rbac.account_role_for_user(
            user,
            object(),
        ) == "owner"

        assert customer_rbac.instance_profile(
            user,
            "cli-000001-dayz-001",
            object(),
        ) == "manager"

    assert calls == [
        ("role", 1, "aurora"),
        ("require", 1, "cli-000001-dayz-001"),
        ("profile", 1, "aurora", "cli-000001-dayz-001"),
    ]
