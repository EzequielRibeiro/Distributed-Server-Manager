# Web authentication and browser sessions

## Scope

Capivara DSM separates four authentication domains:

1. **Controller/Admin browser** — `/login.html`, roles `admin`, `controller`, and `operator`.
2. **Customer browser** — `/customer-login.html`, role `customer` only.
3. **External/commercial APIs** — Bearer/API tokens; browser sessions are not the API credential contract.
4. **Agent ↔ Controller** — Agent identity/credentials; browser credentials are never reused.

A Customer is not a Controller system user. Customer credentials presented to the Controller/Admin login receive the same generic invalid-credential response as an unknown username or incorrect password.

## Browser login contract

Username/password credentials are submitted only for the login request over HTTPS. The frontend may encode them as HTTP Basic for that single credential-verification request, but must not persist the resulting Basic value in `localStorage`, `sessionStorage`, URLs, HTML, or logs.

Successful login creates a random server-side session and returns an HttpOnly cookie. Normal browser navigation and API requests authenticate with that cookie. No authenticated page stores an authentication credential, token, sentinel, or login-state surrogate in Web Storage.

Controller login endpoint:

- `POST /api/auth/login`
- accepts only Controller/system identities (`admin`, `controller`, `operator`)

Customer login endpoint:

- `POST /api/customer/auth/session`
- accepts only canonical Customer identities (`customer`)

Session introspection:

- Controller: `GET /api/auth/session`
- Customer: `GET /api/customer/auth/session`

Logout:

- Controller: `POST /api/auth/logout`
- Customer: `POST /api/customer/auth/logout`
- each logout revokes only its own server-side session and expires only its own cookie

## Cookie policy

The two browser domains use distinct cookies so both identities can coexist in one browser:

- Controller: `capivara_controller_session`
- Customer: `capivara_customer_session`

Both cookies use:

- `HttpOnly`
- `SameSite=Strict`
- `Path=/`
- `Max-Age`
- `Expires`
- `Secure` when `DSM_WEB_SCHEME=https` or `DSM_SESSION_COOKIE_SECURE` explicitly enables it

The default TTL remains eight hours and can be configured with `DSM_BROWSER_SESSION_TTL_SECONDS`.

`DSM_BROWSER_SESSION_FILE` controls the persistent Controller-local session registry. The default is `${DSM_ROOT:-/opt/dsm}/runtime/browser-sessions.json`. Only SHA-256 digests of browser session tokens are persisted; raw cookie tokens are not written to disk. The file is written atomically and restricted to mode `0600` when the filesystem permits it.

Every persisted browser session records its authentication area. A Controller cookie cannot be accepted as a Customer session and a Customer cookie cannot be accepted as a Controller session.

## Shared API route disambiguation

Some historical API routes, such as `/api/whoami` and runtime endpoints, are shared by both portals. Because a browser may legitimately hold both HttpOnly cookies at the same time, authenticated frontend requests identify the intended authentication domain with:

- `X-Capivara-Auth-Area: controller`, or
- `X-Capivara-Auth-Area: customer`.

This header is **not a credential and never grants access**. It only selects which already-valid HttpOnly cookie the server is allowed to evaluate. The role and scope still come exclusively from the validated server-side session.

If both browser sessions coexist and a shared route supplies no unambiguous area, compatibility authentication fails closed rather than guessing an identity.

## Persistence and revocation

The persistent registry allows a valid browser session to survive:

- mobile application switching and browser process reclamation;
- desktop tab/browser restart while the persistent cookie is still valid;
- Dashboard/Controller process restart.

A new login rotates only the session for the same authentication area. Controller and Customer sessions therefore do not revoke one another. Logout revokes only the selected area. Expired sessions are removed when encountered.

`revoke_user_sessions()` is available to security-sensitive account workflows that need to invalidate browser sessions for one identity, for example after password or account-security changes.

## Frontend migration rule

The authenticated frontend is cookie-only. The former `sessionStorage.dsm_auth` / `sessionStorage.dsm_customer_auth` model is retired and must not be reintroduced.

Authenticated modules must not:

- read or write `dsm_auth` or `dsm_customer_auth`;
- clear Web Storage as an authentication operation;
- construct or send `Authorization: Basic ...` after login;
- infer authentication from the presence of a JavaScript value;
- route a Customer 401 response to `/login.html`.

The only permitted browser `Authorization: Basic ...` construction is the initial credential exchange in `auth.js` and `customer-auth.js`. Those values exist only in memory for that request and are immediately discarded.

`browser-session-bridge.js` no longer contains a credential sentinel or Web Storage compatibility state. Its remaining responsibility is request-area compatibility for pages that have not yet consolidated on the canonical browser helper. New or modified authenticated modules should use an explicit auth area and same-origin cookie requests directly.

`tests/browser_auth_legacy_dependency_test.py` scans the browser frontend and fails CI if the retired model is reintroduced.

## Security boundaries

- Login failure messages are intentionally generic: `Usuário ou senha inválidos.`
- Login endpoints are rate-limited.
- Session identifiers are generated with a cryptographically secure random generator.
- Raw session identifiers are not persisted server-side.
- Browser session cookies are inaccessible to JavaScript because of `HttpOnly`.
- `SameSite=Strict` is the primary CSRF boundary for browser-session requests; state-changing browser endpoints must remain same-site and must not weaken this cookie policy without adding an explicit CSRF token/origin policy.
- Browser sessions never replace Bearer tokens for commercial/external APIs or Agent credentials.
- Authentication-area selection is routing metadata, not authorization; RBAC and customer scoping remain server-side.

## Homologation requirements

Before release, validate both Controller/Admin and Customer flows on desktop and mobile. A valid session must survive switching applications, closing/reopening a tab or browser, and restarting the Dashboard service while still inside TTL. Validate simultaneous Controller + Customer sessions, independent logout, expiry, generic rejection of Customer credentials on `/login.html`, Customer login only through `/customer-login.html`, protected static assets, and normal API calls with no persisted Basic credential.

Release/version changes are performed only after homologation passes.
