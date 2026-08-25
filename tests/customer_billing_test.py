from __future__ import annotations

import pytest

from database.customer_billing import (
    billing_unique_key,
    normalize_billing_identity,
)


def test_customer_may_exist_without_billing():
    billing = normalize_billing_identity()
    assert billing.as_dict() == {
        "provider": None,
        "customer_id": None,
        "status": None,
        "linked": False,
    }
    assert billing_unique_key(billing) is None


def test_linked_billing_identity_is_normalized():
    billing = normalize_billing_identity(
        provider=" Stripe ",
        customer_id=" cus_123 ",
    )
    assert billing.provider == "stripe"
    assert billing.customer_id == "cus_123"
    assert billing.status == "active"
    assert billing_unique_key(billing) == ("stripe", "cus_123")


def test_partial_billing_identity_is_rejected():
    with pytest.raises(ValueError, match="supplied together"):
        normalize_billing_identity(provider="stripe")
    with pytest.raises(ValueError, match="supplied together"):
        normalize_billing_identity(customer_id="cus_123")


def test_invalid_billing_status_is_rejected():
    with pytest.raises(ValueError, match="invalid billing status"):
        normalize_billing_identity(
            provider="stripe",
            customer_id="cus_123",
            status="whatever",
        )


def test_unlinked_customer_cannot_claim_active_billing():
    with pytest.raises(ValueError, match="requires a linked"):
        normalize_billing_identity(status="active")
