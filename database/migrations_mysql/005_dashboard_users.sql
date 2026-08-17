-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 005
-- Dashboard users, permissions and audit
-- =============================================================

CREATE TABLE dashboard_users (
    username VARCHAR(191) NOT NULL,

    password_hash VARCHAR(512) NOT NULL,

    role VARCHAR(32) NOT NULL,

    scope_id VARCHAR(191),

    active BOOLEAN NOT NULL
        DEFAULT TRUE,

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (username),

    CONSTRAINT chk_dashboard_users_role
        CHECK (
            role IN (
                'admin',
                'controller',
                'customer',
                'operator'
            )
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE instance_access (
    username VARCHAR(191) NOT NULL,

    instance_id VARCHAR(191) NOT NULL,

    permission_profile VARCHAR(32) NOT NULL
        DEFAULT 'viewer',

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (
        username,
        instance_id
    ),

    CONSTRAINT chk_instance_access_profile
        CHECK (
            permission_profile IN (
                'viewer',
                'operator',
                'manager'
            )
        ),

    CONSTRAINT fk_instance_access_user
        FOREIGN KEY (username)
        REFERENCES dashboard_users(username)
        ON DELETE CASCADE,

    CONSTRAINT fk_instance_access_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE audit_log (
    id BIGINT UNSIGNED NOT NULL
        AUTO_INCREMENT,

    username VARCHAR(191) NOT NULL,

    instance_id VARCHAR(191),

    action VARCHAR(191) NOT NULL,

    result VARCHAR(191) NOT NULL,

    details LONGTEXT,

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE INDEX idx_dashboard_users_role_scope
    ON dashboard_users(
        role,
        scope_id,
        active
    );

CREATE INDEX idx_audit_log_instance_created
    ON audit_log(
        instance_id,
        created_at
    );
