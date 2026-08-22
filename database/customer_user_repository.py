#!/usr/bin/env python3
"""Canonical persistence facade for Customer users, team roles and instance access.

The historical CustomerTeamRepository remains the storage implementation while
this facade gives C7+ callers one stable, user-oriented persistence boundary.
"""
from __future__ import annotations

from customer_team_repository import (
    ACCOUNT_ROLES,
    DELEGABLE_ACCOUNT_ROLES,
    INSTANCE_PROFILES,
    CustomerTeamRepository,
)


class CustomerUserRepository(CustomerTeamRepository):
    """Persistence boundary for Customer user lifecycle and delegated access."""

    def require_membership(self, customer_id: str, username: str) -> str:
        role = self.account_role(customer_id, username)
        if role is None:
            raise PermissionError("customer account membership is required")
        return role

    def require_instance(self, customer_id: str, instance_id: str) -> dict:
        instance_id = str(instance_id).strip()
        for instance in self.list_instances(customer_id):
            if str(instance.get("id")) == instance_id:
                return instance
        raise PermissionError("instance is outside customer scope")

    def owner_count(self, customer_id: str) -> int:
        return sum(1 for member in self.list_members(customer_id) if member.get("account_role") == "owner")


__all__ = [
    "ACCOUNT_ROLES",
    "DELEGABLE_ACCOUNT_ROLES",
    "INSTANCE_PROFILES",
    "CustomerUserRepository",
]
