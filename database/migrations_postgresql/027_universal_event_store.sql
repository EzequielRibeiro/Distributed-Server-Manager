-- Capivara DSM - Migration 027 - PostgreSQL
-- Extend the original events table for the Universal Event Platform.

ALTER TABLE events ADD COLUMN event_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE events ADD COLUMN occurred_at TEXT;
ALTER TABLE events ADD COLUMN source_type TEXT;
ALTER TABLE events ADD COLUMN source_id TEXT;
ALTER TABLE events ADD COLUMN controller_id TEXT;
ALTER TABLE events ADD COLUMN agent_id TEXT;
ALTER TABLE events ADD COLUMN customer_id TEXT;
ALTER TABLE events ADD COLUMN correlation_id TEXT;
ALTER TABLE events ADD COLUMN causation_id TEXT;

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
