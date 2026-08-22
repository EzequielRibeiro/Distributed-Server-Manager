# Customer identity and access — 4.3E to 4.3W

This package closes the customer identity/access sequence while keeping the legacy dashboard transport thin.

## Identity domains

`customers` represents the contracting person/company. `dashboard_users` represents login accounts. `customer_account_members` binds many login accounts to one Customer and gives each account an account role (`owner`, `manager`, `member`). `instance_access` remains independent and carries only per-instance profiles (`viewer`, `operator`, `manager`).

`customer_user_identities` stores the verified e-mail for each customer login. The Customer-level `sftp_username` remains a technical identifier and is not changed when the contact e-mail later changes.

A customer login therefore has two distinct authorization layers:

```text
dashboard_users
  role=customer
  scope_id=<customer-id>

customer_account_members
  customer_id=<customer-id>
  account_role=owner|manager|member
```

The `scope_id` determines the Customer boundary. The membership row determines the account-level role inside that Customer.

## Administrative creation

For a new Customer, use the canonical public CLI:

```bash
cap customer create --id CLIENTE-001 --name "Cliente Exemplo" --username cliente01
```

The password is collected interactively. Do not place it on the command line.

`cap user add <usuario> customer <scope>` is different: it creates or associates a customer-role login for an already existing scope and does not create the Customer entity itself.

The first operational login of a Customer must have membership role `owner`. Databases created by older versions that contain a scoped `dashboard_users` row but no matching `customer_account_members` row can authenticate the Basic credentials while still being rejected by `/api/customer/auth/me`. Such databases must be reconciled before the customer portal is considered healthy.

The generic CLI workflow for Customer, Contract and Instance is documented in `docs/administracao-customer-contract-instance.md`.

## Web login surfaces

Administrative and customer login pages are intentionally separate:

```text
/login.html           administrative access
/customer-login.html  customer access
```

Authenticated routing is role-aware:

```text
customer                    -> /customer.html
admin/controller/operator   -> /index.html
```

Customer pages include:

```text
/customer.html
/customer-members.html
/customer-instance.html
```

A customer must not be redirected to administrative pages such as `/index.html` or `/contract-demo.html`. Games visible in the customer catalog without an active contract remain inside the customer area and present a contracting message instead of navigating into an administrative route.

## Invitations

Only the Customer `owner` can create or revoke invitations. An invitation stores a SHA-256 token digest, expiration, delegated account role and the initial set of instance grants. Accepting the token creates the login inside the same `scope_id`, marks the invited e-mail verified and copies only the selected grants into `instance_access`.

## Registration and e-mail verification

Self-registration creates a `pending` Customer account with an inactive web login. A one-time verification token is stored only as a SHA-256 digest. Verification activates the login, marks both the login e-mail and Customer e-mail verified, and moves `registration_status` to `active`.

SMTP delivery uses `DSM_SMTP_HOST`, `DSM_SMTP_PORT`, `DSM_SMTP_FROM`, optional `DSM_SMTP_USER`/`DSM_SMTP_PASSWORD`, `DSM_SMTP_STARTTLS`, and `DSM_PUBLIC_BASE_URL`. Development-only token exposure is available through `DSM_CUSTOMER_VERIFICATION_EXPOSE_TOKEN` and `DSM_CUSTOMER_INVITATION_EXPOSE_TOKEN`.

## Authentication and recovery

Customer Basic authentication accepts either the technical web username or a verified e-mail. Administrative authentication remains unchanged. Password recovery is enumeration-resistant, uses one-time expiring token hashes, and password change plus token consumption occur atomically in one database transaction.

`/api/customer/auth/me` is the customer identity check used by the dedicated customer login. A successful response requires a valid customer login, a Customer scope and a valid Customer membership.

## Account roles and instance permissions

Account roles and instance permission profiles are intentionally independent:

```text
Account role
  owner
  manager
  member

Per-instance permission profile
  viewer
  operator
  manager
```

`owner` is an account-level capability and is not an instance permission profile. Likewise, a per-instance `manager` profile does not make the login owner or manager of the Customer account.

## Audit and security

Customer registration, verification, recovery/reset, invitation create/revoke/accept, member creation/removal/role changes and instance access changes write to `audit_log`. Public onboarding endpoints and authenticated team mutation endpoints are rate limited. Customer/instance scope is validated before delegated grants are written or resolved.

## Database parity

Migrations 014 through 018 have SQLite, PostgreSQL and MySQL variants. Migration parity checks cover identity, membership, single-owner integrity, invitations, per-login e-mail identity and e-mail verification.

## Operational troubleshooting

If `cap user list` shows a customer as active but the customer login returns `Credenciais de cliente inválidas`, verify these conditions in order:

1. the login has `role=customer`;
2. `scope_id` points to the expected Customer;
3. the Customer is active;
4. `customer_account_members` contains the same username and Customer ID;
5. the first account has a valid account role, normally `owner`;
6. the Dashboard process is using the same configured database as the CLI.

When the deployment uses PostgreSQL or MySQL, diagnostic Python commands must load the same `DSM_DATABASE_*` environment used by the Dashboard. Otherwise `runtime_backend.py` can fall back to the default SQLite configuration and inspect the wrong database.

## Validation

The implementation includes isolation tests, rate-limiter tests, migration parity tests, invitation/verification one-use tests, audit tests and atomic recovery tests. PostgreSQL/MySQL migrations are checked for semantic parity in the repository; live-engine execution still depends on CI or an environment providing those database servers.
