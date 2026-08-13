-- =============================================================
-- Capivara DSM
-- Migration 008
-- Instance runtime selection metadata
-- =============================================================
-- Migration 001 already creates edition, runtime_id and version.
-- Dashboard provisioning additionally persists the fields below.
-- Keep migration history additive: do not recreate columns owned by 001.

ALTER TABLE instances ADD COLUMN variant TEXT;
ALTER TABLE instances ADD COLUMN game_version TEXT;
ALTER TABLE instances ADD COLUMN build_id TEXT;
