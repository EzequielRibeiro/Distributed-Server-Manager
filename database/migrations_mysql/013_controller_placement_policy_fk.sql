-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 013
-- Enforce Controller ownership for placement policies
-- =============================================================

ALTER TABLE controller_placement_policies
    ADD CONSTRAINT fk_controller_placement_policies_controller
    FOREIGN KEY (controller_id)
    REFERENCES controllers(id)
    ON DELETE CASCADE;
