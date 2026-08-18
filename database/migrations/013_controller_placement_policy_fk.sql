-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 013
-- Enforce Controller ownership for placement policies
-- =============================================================
CREATE TABLE controller_placement_policies_new (
    controller_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'latency_assisted'
        CHECK (mode IN (
            'controller',
            'customer_region',
            'latency_assisted'
        )),
    customer_region_selection INTEGER NOT NULL DEFAULT 1
        CHECK (customer_region_selection IN (0, 1)),
    cross_region_fallback INTEGER NOT NULL DEFAULT 0
        CHECK (cross_region_fallback IN (0, 1)),
    max_latency_ms INTEGER,
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    FOREIGN KEY (controller_id)
        REFERENCES controllers(id)
        ON DELETE CASCADE
);
INSERT INTO controller_placement_policies_new (
    controller_id,
    mode,
    customer_region_selection,
    cross_region_fallback,
    max_latency_ms,
    updated_at
)
SELECT
    controller_id,
    mode,
    customer_region_selection,
    cross_region_fallback,
    max_latency_ms,
    updated_at
FROM controller_placement_policies;
DROP TABLE controller_placement_policies;
ALTER TABLE controller_placement_policies_new
    RENAME TO controller_placement_policies;
