-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 019
-- Legacy customer account membership and identity backfill
-- PostgreSQL
-- =============================================================

-- -------------------------------------------------------------
-- 1. Restore missing legacy customer ownership.
--
-- A legacy customer user becomes owner only when:
--   * it belongs to the customer through scope_id;
--   * it has no membership yet;
--   * that customer has no owner yet.
--
-- Existing memberships and owners are preserved.
-- -------------------------------------------------------------

INSERT INTO customer_account_members (
    customer_id,
    username,
    account_role
)
SELECT
    c.id,
    u.username,
    'owner'
FROM dashboard_users u
JOIN customers c
    ON c.id = u.scope_id
WHERE u.role = 'customer'
  AND NOT EXISTS (
      SELECT 1
      FROM customer_account_members m
      WHERE m.customer_id = c.id
        AND m.username = u.username
  )
  AND NOT EXISTS (
      SELECT 1
      FROM customer_account_members owner_account
      WHERE owner_account.customer_id = c.id
        AND owner_account.account_role = 'owner'
  );

-- -------------------------------------------------------------
-- 2. Restore the login identity for customer owners.
--
-- Migration 017 originally backfilled existing owners.
-- Legacy users without membership were therefore not included.
--
-- Existing identities are preserved.
-- -------------------------------------------------------------

INSERT INTO customer_user_identities (
    username,
    email,
    email_verified_at
)
SELECT
    m.username,
    c.account_email,
    c.email_verified_at
FROM customer_account_members m
JOIN customers c
    ON c.id = m.customer_id
WHERE m.account_role = 'owner'
  AND c.account_email IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM customer_user_identities i
      WHERE i.username = m.username
  );
