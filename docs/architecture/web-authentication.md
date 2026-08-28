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

Successful login creates a random server-side session and returns an HttpOnly cookie. Normal browser navigation and API requests authenticate with that cookie.

Controller login endpoint:

- `POST /api/auth/login`
- accepts only Controller/system identities (`admin`, `controller`, `operator`)

Customer login endpoint:

- `POST /api/customer/auth/session`
- accepts only canonical Customer identities (`customer`)

Session introspection:

- `GET /api/auth/session`

Logout:

- `POST /api/auth/logout`
- revokes the server-side session and expires the browser cookie

## Cookie policy

The session cookie is `capivara_session` and uses:

- `HttpOnly`
- `SameSite=Strict`
- `Path=/`
- `Max-Age`
- `Expires`
- `Secure` when `DSM_WEB_SCHEME=https` or `DSM_SESSION_COOKIE_SECURE` explicitly enables it

The default TTL remains eight hours and can be configured with `DSM_BROWSER_SESSION_TTL_SECONDS`.

`DSM_BROWSER_SESSION_FILE` controls the persistent Controller-local session registry. The default is `${DSM_ROOT:-/opt/dsm}/runtime/browser-sessions.json`. Only SHA-256 digests of browser session tokens are persisted; the raw cookie token is not written to disk. The file is written atomically and restricted to mode `0600` when the filesystem permits it.

## Persistence and revocation

The persistent registry allows a valid browser session to survive:

- mobile application switching and browser process reclamation;
- desktop tab/browser restart while the persistent cookie is still valid;
- Dashboard/Controller process restart.

A new login rotates the session token by revoking the current browser session before creating a replacement. Logout revokes it immediately. Expired sessions are removed when encountered.

`revoke_user_sessions()` is available to security-sensitive account workflows that need to invalidate every browser session for one identity, for example after password or account-security changes.

## Legacy frontend compatibility

Some Dashboard modules still synchronously test for `sessionStorage.dsm_auth` before making a request. During migration, authenticated HTML pages load `browser-session-bridge.js` before legacy modules.

The bridge writes only the fixed, non-secret sentinel `cookie-session`; it never writes username/password-derived Basic credentials. It also strips the sentinel `Authorization` header before `fetch()` reaches the network, so actual browser authentication remains cookie-only.

This bridge is transitional compatibility code. New frontend code must not depend on `dsm_auth` and should use ordinary same-origin `fetch()` calls.

## Security boundaries

- Login failure messages are intentionally generic: `Usuário ou senha inválidos.`
- Login endpoints are rate-limited.
- Session identifiers are generated with a cryptographically secure random generator.
- Raw session identifiers are not persisted server-side.
- Browser session cookies are inaccessible to JavaScript because of `HttpOnly`.
- `SameSite=Strict` is the primary CSRF boundary for browser-session requests; state-changing browser endpoints must remain same-site and must not weaken this cookie policy without adding an explicit CSRF token/origin policy.
- Browser sessions never replace Bearer tokens for commercial/external APIs or Agent credentials.

## Homologation requirements

Before release, validate both Controller/Admin and Customer flows on desktop and mobile. A valid session must survive switching applications, closing/reopening a tab or browser, and restarting the Dashboard service while still inside TTL. Validate generic rejection of Customer credentials on `/login.html`, Customer login only through `/customer-login.html`, logout revocation, expiry, protected static assets, and normal API calls with no persisted Basic credential.

Release/version changes are performed only after homologation passes.
