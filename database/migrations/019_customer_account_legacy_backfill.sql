-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 019
-- Legacy customer account membership and identity backfill
--
-- Purpose:
--   Migrate customer users created before the customer-account
--   membership model introduced by migration 015.
--
-- Rules:
--   - Never replace an existing account owner.
--   - Never duplicate an existing membership.
--   - Only customer users whose scope_id matches customers.id
--     are considered.
--   - Backfill the per-login identity only when an account
--     e-mail exists and the username has no identity yet.
-- =============================================================

-- -------------------------------------------------------------
-- 1. Restore missing legacy customer ownership.
--
-- A legacy customer user becomes owner only when:
--   * it belongs to the customer through scope_id;
--   * it has no membership yet;
--   * that customer has no owner yet.
--
-- The NOT EXISTS checks make this safe for databases where
-- migrations 015-018 have already been partially populated.
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
      FROM customer_account_members owner
      WHERE owner.customer_id = c.id
        AND owner.account_role = 'owner'
  );


-- -------------------------------------------------------------
-- 2. Restore the login identity for customer owners.
--
-- Migration 017 originally performed this operation, but legacy
-- users without a membership were not visible to that backfill.
--
-- Only accounts with an account_email are considered.
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
