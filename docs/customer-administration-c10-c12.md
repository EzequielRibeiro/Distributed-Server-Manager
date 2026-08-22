# Customer Administration — C10 to C12

## C10 — Ownership lifecycle

Customer ownership is transferable only by the authenticated current Owner. The
target must already be an active member of the same Customer. Transfer is atomic:
the previous Owner becomes Manager and the target becomes Owner in one database
transaction. A caller cannot supply an alternate `customer_id`; scope comes from
the authenticated Customer session.

## C11 — Customer user lifecycle

The Owner can temporarily disable or reactivate delegated Customer logins and
reset their passwords without deleting membership or instance grants. The Owner
account itself cannot be disabled. Permanent removal remains a separate action.
This keeps temporary access suspension distinct from destructive deletion.

## C12 — Security closure and audit

The Customer team surface exposes a Customer-scoped activity feed backed by
`audit_log`. Team, ownership, password and instance-access changes are recorded
with Customer context. Activity queries are constrained to usernames that are
members of the authenticated Customer and instances owned by that Customer.

C10-C12 have a dedicated CI gate covering Python syntax, JavaScript syntax,
ownership/lifecycle contracts, session-bound scope and the customer UI surface.
