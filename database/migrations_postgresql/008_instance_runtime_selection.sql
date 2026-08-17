-- =============================================================
-- Capivara Distributed Server Manager
-- PostgreSQL Migration 008
-- Instance runtime selection metadata
-- =============================================================

ALTER TABLE instances
    ADD COLUMN variant TEXT;

ALTER TABLE instances
    ADD COLUMN game_version TEXT;

ALTER TABLE instances
    ADD COLUMN build_id TEXT;
