# Passkey (WebAuthn) Passwordless Authentication

**Date**: 2026-04-04
**Status**: Draft
**Libraries**: `py_webauthn` (backend), `@simplewebauthn/browser` (frontend)

## Summary

Add passkey/WebAuthn support as a passwordless login option. Users register passkeys in profile settings and use them as the primary sign-in method. Password login remains always available as a fallback. Passkey login bypasses TOTP 2FA (passkeys are inherently multi-factor); password login continues to enforce TOTP when enabled.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Login UX | Passkey-first (discoverable credentials) | Prominent "Sign in with passkey" button, password form below with "or" divider. Browser shows credential picker — no email required. |
| Registration UX | Profile settings only | No onboarding prompt, no post-login nudge. Users add passkeys in `/profile/passkeys`. |
| Password fallback | Always available | Passkeys can be lost (device stolen, browser reset). Password is the universal fallback. |
| Passkey + TOTP interaction | Either/or | Passkey login skips TOTP. Password login still requires TOTP if enabled. |
| Max passkeys per user | 10 | Generous enough for all real devices, prevents abuse. Enforced at service layer. |
| Passkey deletion | Requires password re-auth | Prevents attacker with stolen session from silently removing credentials. Same pattern as TOTP disable. |
| Attestation | None | Accept `"none"` attestation — no hardware verification. Same stance as GitHub/Google. |
| Libraries | `py_webauthn` + `@simplewebauthn/browser` | Standard pairing, well-maintained, handles encoding/CBOR/format negotiation. |

## Data Model

### WebAuthnCredential (embedded sub-document on User)

```python
class WebAuthnCredential(BaseModel):
    credential_id: bytes          # Unique identifier from authenticator
    public_key: bytes             # For assertion verification
    sign_count: int               # Replay attack detection
    transports: list[str]         # ["internal", "usb", "ble", "nfc"] — browser hints
    name: str                     # User-given label ("MacBook Touch ID")
    aaguid: str                   # Authenticator type identifier
    created_at: datetime
    last_used_at: datetime | None = None
```

Added to the `User` model:

```python
webauthn_credentials: list[WebAuthnCredential] = []
```

MongoDB index on `webauthn_credentials.credential_id` for fast user lookup during discoverable login.

**Encoding note**: `credential_id` and `public_key` are stored as `bytes` in MongoDB. All API inputs/outputs use base64url encoding for these fields. `py_webauthn` handles the conversion internally; the service layer stores/retrieves raw bytes.

### Challenge Storage (Redis)

Key: `webauthn:challenge:{session_id}` (UUID session_id generated per challenge)
TTL: 5 minutes
Value:
```json
{
  "challenge": "<base64url-encoded bytes>",
  "user_id": "<ObjectId string or null>",
  "type": "registration | authentication"
}
```

Deleted on use (verify step). No new MongoDB collections.

## Backend API Endpoints

All under `/api/v1/auth/passkey/`.

### Registration (authenticated)

**`POST /auth/passkey/register/begin`**
- Requires: `get_current_user_from_token`
- Generates registration challenge via `py_webauthn`
- Options include: RP name/id, user info (id, email, display name), excluded existing credential IDs
- Stores challenge in Redis
- Returns: `{ session_id, options }` (options = `PublicKeyCredentialCreationOptions` JSON)

**`POST /auth/passkey/register/complete`**
- Requires: `get_current_user_from_token`
- Body: `{ session_id, credential, name }`
- Retrieves challenge from Redis (fails if expired/missing)
- Verifies attestation via `py_webauthn`
- Checks credential count < 10
- Appends `WebAuthnCredential` to user, saves
- Deletes challenge from Redis
- Returns: passkey summary (id, name, created_at)

### Authentication (unauthenticated)

**`POST /auth/passkey/login/begin`**
- No auth required, rate-limited (reuse existing IP-based limiter)
- Generates authentication challenge with empty `allowCredentials` (discoverable)
- Stores challenge in Redis
- Returns: `{ session_id, options }` (options = `PublicKeyCredentialRequestOptions` JSON)

**`POST /auth/passkey/login/complete`**
- Body: `{ session_id, credential }`
- Retrieves challenge from Redis
- Extracts `credential_id` from assertion response
- Finds user by `credential_id` (indexed query)
- Verifies assertion via `py_webauthn` (signature, origin, RP ID)
- Updates `sign_count` and `last_used_at` on the matched credential
- Sign count regression: log warning, do not block (synced passkeys may not increment)
- Creates JWT + UserSession (same logic as password login)
- Returns: `TokenResponse` (access_token, token_type, expires_in)

### Management (authenticated)

**`GET /auth/passkeys`**
- Requires: `get_current_user_from_token`
- Returns: list of `{ id, name, created_at, last_used_at, transports }` — no secret material

**`DELETE /auth/passkey/{credential_id}`**
- Requires: `get_current_user_from_token`
- Body: `{ password }` — re-authentication required
- Verifies password, then removes matching credential from user's list
- `credential_id` is base64url-encoded in path

## Backend Service Layer

### PasskeyService (`app/services/passkey_service.py`)

Async class, takes Redis client as dependency.

**Methods:**

- `generate_registration_options(user) -> (session_id, options_dict)` — Builds options via `py_webauthn`, excludes existing credentials, stores challenge in Redis.

- `verify_registration(user, session_id, credential, name) -> WebAuthnCredential` — Retrieves + deletes challenge from Redis, verifies via `py_webauthn`, enforces max 10 credentials, appends to user, saves, returns credential.

- `generate_authentication_options() -> (session_id, options_dict)` — Builds discoverable options (empty `allowCredentials`), stores challenge in Redis.

- `verify_authentication(session_id, credential) -> User` — Retrieves + deletes challenge from Redis, finds user by `credential_id`, verifies assertion, updates sign count + last_used_at, returns User. JWT/session creation stays in route handler.

- `list_passkeys(user) -> list[dict]` — Sanitized list, no public keys or sign counts.

- `delete_passkey(user, credential_id) -> None` — Removes matching credential, saves. Password verification done in route handler before calling this.

### Redis Client

Async wrapper using `redis.asyncio` from the existing `redis>=5.2.0` dependency. Connects to the same Redis instance used by Celery. New module: `app/core/redis_client.py` with `get_redis()` async dependency.

## Frontend

### PasskeyService (`core/services/passkey.service.ts`)

- `isSupported(): boolean` — Checks `window.PublicKeyCredential` availability
- `register(name: string): Observable<PasskeyResponse>` — Full flow: calls begin, invokes `startRegistration()` from `@simplewebauthn/browser`, calls complete
- `login(): Observable<TokenResponse>` — Full flow: calls begin, invokes `startAuthentication()`, calls complete
- `listPasskeys(): Observable<PasskeyResponse[]>` — GET /auth/passkeys
- `deletePasskey(credentialId: string, password: string): Observable<void>` — DELETE with password body

### Login Component Changes

- On init, check `passkeyService.isSupported()`
- If supported: show "Sign in with passkey" button prominently above the email/password form, separated by an "or" divider
- Button click: `passkeyService.login()` → `tokenService.setToken()` → dispatch `AuthActions.loginSuccess()`
- On WebAuthn cancel/failure: dismiss silently, user can use password
- Existing email/password form unchanged
- No new NgRx actions — passkey login resolves to the same `TokenResponse` and uses existing `loginSuccess` path

### PasskeysComponent (`features/profile/passkeys/`)

New route: `/profile/passkeys` added to profile routes.

- Signal-based: `passkeys = signal<PasskeyResponse[]>([])`, `loading = signal(false)`
- Table columns: Name, Created, Last Used, Actions (delete)
- "Add passkey" button — opens dialog for name input, triggers `passkeyService.register(name)`
- Delete button — opens confirmation dialog with password input field, calls `passkeyService.deletePasskey(id, password)`
- Empty state message: "No passkeys registered. Add one for faster sign-in."
- Profile nav: add "Passkeys" tab alongside General, Password, Sessions

### Models (`core/models/passkey.model.ts`)

```typescript
export interface PasskeyResponse {
  id: string;              // base64url credential_id
  name: string;
  created_at: string;
  last_used_at: string | null;
  transports: string[];
}
```

Registration/authentication option types provided by `@simplewebauthn/browser`.

## Configuration

Three new environment variables in `app/config.py`:

```python
webauthn_rp_id: str = "localhost"         # Relying Party ID — must match domain
webauthn_rp_name: str = "Mist Automation" # Human-readable name in browser prompts
webauthn_origin: str = "http://localhost:4200"  # Expected origin for verification
```

Deployment-specific, no admin UI needed.

### Health Endpoint

Add `passkey_support: true` to `/health` response so the frontend can conditionally show passkey UI.

## Security

| Concern | Mitigation |
|---------|------------|
| Challenge replay | Redis 5-min TTL + delete-on-use |
| Credential cloning | Sign count regression detection (warn, don't block) |
| Phishing | WebAuthn origin verification (automatic) |
| CSRF | Challenge-response pattern inherently CSRF-resistant |
| Brute force on login/begin | Reuse existing IP-based rate limiter |
| Stolen session → passkey removal | Password re-authentication required for deletion |
| Account enumeration | login/begin returns identical response regardless of user existence |
| Attestation bypass | Accepted risk — `"none"` attestation, same as GitHub/Google |
| Synced passkey sign count | Warning-only on regression — synced authenticators (iCloud, Google) may not increment |

## Out of Scope

- Passkey registration during onboarding
- Post-login passkey setup nudge/banner
- Admin enforcement of passkey-only login
- Hardware attestation verification
- Configurable max passkey count (hardcoded to 10)
- Conditional UI / autofill integration (future enhancement)
- Passkey as TOTP replacement in admin settings
