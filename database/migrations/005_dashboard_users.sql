CREATE TABLE dashboard_users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','controller','customer','operator')),
    scope_id TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE instance_access (
    username TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    permission_profile TEXT NOT NULL DEFAULT 'viewer'
        CHECK (permission_profile IN ('viewer','operator','manager')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (username, instance_id),
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    instance_id TEXT,
    action TEXT NOT NULL,
    result TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_dashboard_users_role_scope
    ON dashboard_users(role, scope_id, active);
CREATE INDEX idx_audit_log_instance_created
    ON audit_log(instance_id, created_at);
