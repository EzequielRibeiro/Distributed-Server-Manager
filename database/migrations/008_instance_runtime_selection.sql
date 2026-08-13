-- Persist the runtime selection used to provision each instance.
-- These fields are written by dashboard/server.py when a customer creates
-- an instance and must exist for both new and upgraded databases.

ALTER TABLE instances ADD COLUMN runtime_id TEXT;
ALTER TABLE instances ADD COLUMN edition TEXT;
ALTER TABLE instances ADD COLUMN variant TEXT;
ALTER TABLE instances ADD COLUMN game_version TEXT;
ALTER TABLE instances ADD COLUMN build_id TEXT;
