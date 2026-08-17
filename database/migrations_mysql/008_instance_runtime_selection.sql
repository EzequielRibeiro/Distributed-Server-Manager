-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 008
-- Instance runtime selection metadata
-- =============================================================

ALTER TABLE instances
    ADD COLUMN variant VARCHAR(191);

ALTER TABLE instances
    ADD COLUMN game_version VARCHAR(191);

ALTER TABLE instances
    ADD COLUMN build_id VARCHAR(191);
