-- Capivara DSM - Migration 029 - MySQL/MariaDB
-- Extend the original events table for the Universal Event Platform.

ALTER TABLE events
    ADD COLUMN event_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN occurred_at VARCHAR(40),
    ADD COLUMN source_type VARCHAR(64),
    ADD COLUMN source_id VARCHAR(191),
    ADD COLUMN controller_id VARCHAR(191),
    ADD COLUMN agent_id VARCHAR(191),
    ADD COLUMN customer_id VARCHAR(191),
    ADD COLUMN correlation_id VARCHAR(191),
    ADD COLUMN causation_id VARCHAR(191);

CREATE INDEX idx_events_type_occurred
    ON events(event_type, occurred_at);
CREATE INDEX idx_events_agent_occurred
    ON events(agent_id, occurred_at);
CREATE INDEX idx_events_customer_occurred
    ON events(customer_id, occurred_at);
CREATE INDEX idx_events_instance_occurred
    ON events(instance_id, occurred_at);
CREATE INDEX idx_events_correlation
    ON events(correlation_id);
