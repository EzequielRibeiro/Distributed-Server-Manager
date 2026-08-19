# Customer identity and access — 4.3E to 4.3W

This package closes the customer identity/access sequence while keeping the legacy dashboard transport thin.

## Identity domains

`customers` represents the contracting person/company. `dashboard_users` represents login accounts. `customer_account_members` binds many login accounts to one Customer and gives each account an account role (`owner`, `manager`, `member`). `instance_access` remains independent and carries only per-instance profiles (`viewer`, `operator`, `manager`).

`customer_user_identities` stores the verified e-mail for each customer login. The Customer-level `sftp_username` remains a technical identifier and is not changed when the contact e-mail later changes.

## Invitations

Only the Customer `owner` can create or revoke invitations. An invitation stores a SHA-256 token digest, expiration, delegated account role and the initial set of instance grants. Accepting the token creates the login inside the same `scope_id`, marks the invited e-mail verified and copies only the selected grants into `instance_access`.

## Registration and e-mail verification

Self-registration creates a `pending` Customer account with an inactive web login. A one-time verification token is stored only as a SHA-256 digest. Verification activates the login, marks both the login e-mail and Customer e-mail verified, and moves `registration_status` to `active`.

SMTP delivery uses `DSM_SMTP_HOST`, `DSM_SMTP_PORT`, `DSM_SMTP_FROM`, optional `DSM_SMTP_USER`/`DSM_SMTP_PASSWORD`, `DSM_SMTP_STARTTLS`, and `DSM_PUBLIC_BASE_URL`. Development-only token exposure is available through `DSM_CUSTOMER_VERIFICATION_EXPOSE_TOKEN` and `DSM_CUSTOMER_INVITATION_EXPOSE_TOKEN`.

## Authentication and recovery

Customer Basic authentication accepts either the technical web username or a verified e-mail. Administrative authentication remains unchanged. Password recovery is enumeration-resistant, uses one-time expiring token hashes, and password change plus token consumption occur atomically in one database transaction.

## Audit and security

Customer registration, verification, recovery/reset, invitation create/revoke/accept, member creation/removal/role changes and instance access changes write to `audit_log`. Public onboarding endpoints and authenticated team mutation endpoints are rate limited. Customer/instance scope is validated before delegated grants are written or resolved.

## Database parity

Migrations 014 through 018 have SQLite, PostgreSQL and MySQL variants. Migration parity checks cover identity, membership, single-owner integrity, invitations, per-login e-mail identity and e-mail verification.

## Validation

The implementation includes isolation tests, rate-limiter tests, migration parity tests, invitation/verification one-use tests, audit tests and atomic recovery tests. PostgreSQL/MySQL migrations are checked for semantic parity in the repository; live-engine execution still depends on CI or an environment providing those database servers.
