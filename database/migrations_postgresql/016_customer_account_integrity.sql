-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 016 - customer_account integrity parity
-- PostgreSQL already enforces a single owner through migration 015.
-- Add the role lookup index present in the MySQL model.
-- =============================================================
CREATE INDEX IF NOT EXISTS idx_customer_account_member_role
    ON customer_account_members(customer_id, account_role);
