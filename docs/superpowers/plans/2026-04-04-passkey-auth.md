# Passkey (WebAuthn) Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add passwordless passkey/WebAuthn login as the primary sign-in method, with password as fallback.

**Architecture:** `py_webauthn` handles server-side challenge generation and verification. `@simplewebauthn/browser` wraps the browser's `navigator.credentials` API. Challenges stored in Redis (5-min TTL). Credentials embedded in the User document. Login page shows passkey-first UX with discoverable credentials.

**Tech Stack:** py_webauthn, @simplewebauthn/browser, redis.asyncio, Angular Material, signals

**Spec:** `docs/superpowers/specs/2026-04-04-passkey-auth-design.md`

---

### Task 1: Install Backend Dependency

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add py_webauthn to dependencies**

In `backend/pyproject.toml`, add `py_webauthn` to the dependencies list (after the existing `pyotp` line):

```toml
    "py_webauthn>=2.0.0",
```

- [ ] **Step 2: Install the dependency**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pip install -e ".[dev,test]"
```

Expected: Installs `py_webauthn` and its dependencies without errors.

- [ ] **Step 3: Verify import**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/python -c "import webauthn; print(webauthn.__version__)"
```

Expected: Prints version number (e.g., `2.2.0`).

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "feat(auth): add py_webauthn dependency for passkey support"
```

---

### Task 2: WebAuthn Credential Model

**Files:**
- Modify: `backend/app/models/user.py`
- Test: `backend/tests/unit/test_passkey_model.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_passkey_model.py`:

```python
"""Tests for WebAuthn credential model on User."""

from datetime import datetime, timezone

import pytest

from app.models.user import User, WebAuthnCredential


def test_webauthn_credential_creation():
    """WebAuthnCredential can be instantiated with required fields."""
    cred = WebAuthnCredential(
        credential_id=b"\x01\x02\x03",
        public_key=b"\x04\x05\x06",
        sign_count=0,
        transports=["internal"],
        name="MacBook Touch ID",
        aaguid="00000000-0000-0000-0000-000000000000",
    )
    assert cred.credential_id == b"\x01\x02\x03"
    assert cred.sign_count == 0
    assert cred.name == "MacBook Touch ID"
    assert cred.last_used_at is None
    assert isinstance(cred.created_at, datetime)


def test_user_default_webauthn_credentials():
    """User model has empty webauthn_credentials by default."""
    user = User(
        email="test@example.com",
        password_hash="fakehash",
        roles=["admin"],
    )
    assert user.webauthn_credentials == []


@pytest.mark.parametrize("count", [0, 1, 3])
def test_user_with_multiple_credentials(count):
    """User can have multiple WebAuthn credentials."""
    creds = [
        WebAuthnCredential(
            credential_id=bytes([i]),
            public_key=bytes([i + 10]),
            sign_count=0,
            transports=["internal"],
            name=f"Key {i}",
            aaguid="00000000-0000-0000-0000-000000000000",
        )
        for i in range(count)
    ]
    user = User(
        email="test@example.com",
        password_hash="fakehash",
        roles=["admin"],
        webauthn_credentials=creds,
    )
    assert len(user.webauthn_credentials) == count
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pytest tests/unit/test_passkey_model.py -v
```

Expected: FAIL with `ImportError: cannot import name 'WebAuthnCredential' from 'app.models.user'`

- [ ] **Step 3: Add WebAuthnCredential model to User**

Modify `backend/app/models/user.py`. Add import at top:

```python
from pydantic import BaseModel, EmailStr, Field
```

(BaseModel is already imported via Beanie, but ensure it's explicit.)

Add the `WebAuthnCredential` class before the `User` class (after line 11):

```python
class WebAuthnCredential(BaseModel):
    """A registered WebAuthn/passkey credential."""

    credential_id: bytes
    public_key: bytes
    sign_count: int = 0
    transports: list[str] = Field(default_factory=list)
    name: str = ""
    aaguid: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: datetime | None = None
```

Add the field to the `User` class, after the TOTP fields (after line 33):

```python
    # WebAuthn / Passkeys
    webauthn_credentials: list[WebAuthnCredential] = Field(
        default_factory=list, description="Registered WebAuthn/passkey credentials"
    )
```

Add a MongoDB index for credential lookup. In `User.Settings.indexes`, add:

```python
    IndexModel([("webauthn_credentials.credential_id", ASCENDING)]),
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pytest tests/unit/test_passkey_model.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/user.py backend/tests/unit/test_passkey_model.py
git commit -m "feat(auth): add WebAuthnCredential model to User"
```

---

### Task 3: Redis Client Utility

**Files:**
- Create: `backend/app/core/redis_client.py`
- Test: `backend/tests/unit/test_redis_client.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_redis_client.py`:

```python
"""Tests for Redis client utility (challenge storage)."""

import pytest

from app.core.redis_client import WebAuthnChallengeStore


@pytest.fixture
def store():
    """Create a store with a mock Redis (dict-based)."""
    return WebAuthnChallengeStore(redis=None)  # Will use internal dict fallback


@pytest.mark.asyncio
async def test_store_and_retrieve_challenge(store):
    """Can store a challenge and retrieve it."""
    await store.store_challenge("sess-1", {"challenge": "abc123", "user_id": "u1", "type": "registration"})
    data = await store.get_challenge("sess-1")
    assert data is not None
    assert data["challenge"] == "abc123"
    assert data["type"] == "registration"


@pytest.mark.asyncio
async def test_get_challenge_deletes_on_retrieve(store):
    """Challenge is deleted after retrieval (single-use)."""
    await store.store_challenge("sess-2", {"challenge": "xyz"})
    data = await store.get_challenge("sess-2")
    assert data is not None
    data2 = await store.get_challenge("sess-2")
    assert data2 is None


@pytest.mark.asyncio
async def test_get_nonexistent_challenge(store):
    """Missing challenge returns None."""
    data = await store.get_challenge("nonexistent")
    assert data is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pytest tests/unit/test_redis_client.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.redis_client'`

- [ ] **Step 3: Implement WebAuthnChallengeStore**

Create `backend/app/core/redis_client.py`:

```python
"""
Redis client utilities for WebAuthn challenge storage.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_CHALLENGE_PREFIX = "webauthn:challenge:"
_CHALLENGE_TTL = 300  # 5 minutes


class WebAuthnChallengeStore:
    """
    Store and retrieve WebAuthn challenges.

    Uses Redis when available, falls back to an in-memory dict for testing.
    Challenges are single-use: retrieved once then deleted.
    """

    def __init__(self, redis: Any | None = None) -> None:
        self._redis = redis
        self._fallback: dict[str, str] = {}

    @staticmethod
    def generate_session_id() -> str:
        return uuid.uuid4().hex

    async def store_challenge(self, session_id: str, data: dict) -> None:
        key = f"{_CHALLENGE_PREFIX}{session_id}"
        payload = json.dumps(data)
        if self._redis is not None:
            await self._redis.set(key, payload, ex=_CHALLENGE_TTL)
        else:
            self._fallback[key] = payload

    async def get_challenge(self, session_id: str) -> dict | None:
        key = f"{_CHALLENGE_PREFIX}{session_id}"
        if self._redis is not None:
            payload = await self._redis.get(key)
            if payload is None:
                return None
            await self._redis.delete(key)
            return json.loads(payload)
        else:
            payload = self._fallback.pop(key, None)
            if payload is None:
                return None
            return json.loads(payload)


_store: WebAuthnChallengeStore | None = None


async def get_challenge_store() -> WebAuthnChallengeStore:
    """Get or create the singleton challenge store."""
    global _store
    if _store is None:
        try:
            from redis.asyncio import from_url

            from app.config import settings

            redis = from_url(settings.redis_url, decode_responses=True)
            _store = WebAuthnChallengeStore(redis=redis)
            logger.info("webauthn_challenge_store_initialized", backend="redis")
        except Exception:
            logger.warning("webauthn_challenge_store_fallback", backend="memory")
            _store = WebAuthnChallengeStore(redis=None)
    return _store
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pytest tests/unit/test_redis_client.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/redis_client.py backend/tests/unit/test_redis_client.py
git commit -m "feat(auth): add WebAuthn challenge store with Redis backend"
```

---

### Task 4: Passkey Service — Registration

**Files:**
- Create: `backend/app/services/passkey_service.py`
- Test: `backend/tests/unit/test_passkey_service.py`

- [ ] **Step 1: Write the failing test for registration**

Create `backend/tests/unit/test_passkey_service.py`:

```python
"""Tests for PasskeyService."""

import pytest
import pytest_asyncio

from app.core.redis_client import WebAuthnChallengeStore
from app.models.user import User, WebAuthnCredential
from app.services.passkey_service import PasskeyService, PasskeyError

MAX_PASSKEYS = 10


@pytest.fixture
def challenge_store():
    return WebAuthnChallengeStore(redis=None)


@pytest.fixture
def service(challenge_store):
    return PasskeyService(
        challenge_store=challenge_store,
        rp_id="localhost",
        rp_name="Test App",
        expected_origin="http://localhost:4200",
    )


def _make_user(**overrides) -> User:
    defaults = dict(email="test@example.com", password_hash="fakehash", roles=["admin"])
    defaults.update(overrides)
    return User(**defaults)


@pytest.mark.asyncio
async def test_generate_registration_options(service):
    """Registration begin returns session_id and options with correct RP info."""
    user = _make_user()
    session_id, options = await service.generate_registration_options(user)
    assert isinstance(session_id, str)
    assert len(session_id) == 32  # uuid4 hex
    assert options["rp"]["id"] == "localhost"
    assert options["rp"]["name"] == "Test App"
    assert options["user"]["name"] == "test@example.com"


@pytest.mark.asyncio
async def test_registration_excludes_existing_credentials(service):
    """Registration options exclude already-registered credential IDs."""
    cred = WebAuthnCredential(
        credential_id=b"\x01\x02\x03",
        public_key=b"\x04\x05\x06",
        sign_count=0,
        transports=["internal"],
        name="Existing Key",
        aaguid="00000000-0000-0000-0000-000000000000",
    )
    user = _make_user(webauthn_credentials=[cred])
    _, options = await service.generate_registration_options(user)
    assert len(options["excludeCredentials"]) == 1


@pytest.mark.asyncio
async def test_max_passkeys_enforced(service):
    """Cannot register more than MAX_PASSKEYS credentials."""
    creds = [
        WebAuthnCredential(
            credential_id=bytes([i]),
            public_key=bytes([i + 10]),
            sign_count=0,
            transports=["internal"],
            name=f"Key {i}",
            aaguid="00000000-0000-0000-0000-000000000000",
        )
        for i in range(MAX_PASSKEYS)
    ]
    user = _make_user(webauthn_credentials=creds)
    with pytest.raises(PasskeyError, match="maximum"):
        await service.generate_registration_options(user)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pytest tests/unit/test_passkey_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.passkey_service'`

- [ ] **Step 3: Implement PasskeyService registration methods**

Create `backend/app/services/passkey_service.py`:

```python
"""
Passkey (WebAuthn) service for registration and authentication.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

import structlog
import webauthn
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.redis_client import WebAuthnChallengeStore
from app.models.user import User, WebAuthnCredential

logger = structlog.get_logger(__name__)

MAX_PASSKEYS = 10


class PasskeyError(Exception):
    """Raised on passkey registration/authentication failures."""


class PasskeyService:
    """Handles WebAuthn registration and authentication flows."""

    def __init__(
        self,
        challenge_store: WebAuthnChallengeStore,
        rp_id: str,
        rp_name: str,
        expected_origin: str,
    ) -> None:
        self._store = challenge_store
        self._rp_id = rp_id
        self._rp_name = rp_name
        self._expected_origin = expected_origin

    async def generate_registration_options(self, user: User) -> tuple[str, dict]:
        """
        Begin passkey registration.
        Returns (session_id, options_dict) for the client.
        """
        if len(user.webauthn_credentials) >= MAX_PASSKEYS:
            raise PasskeyError(f"Cannot register more than {MAX_PASSKEYS} passkeys (maximum reached)")

        exclude_credentials = [
            PublicKeyCredentialDescriptor(
                id=cred.credential_id,
                transports=cred.transports,
            )
            for cred in user.webauthn_credentials
        ]

        options = webauthn.generate_registration_options(
            rp_id=self._rp_id,
            rp_name=self._rp_name,
            user_id=str(user.id).encode(),
            user_name=user.email,
            user_display_name=user.display_name(),
            exclude_credentials=exclude_credentials,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )

        session_id = self._store.generate_session_id()
        await self._store.store_challenge(
            session_id,
            {
                "challenge": bytes_to_base64url(options.challenge),
                "user_id": str(user.id),
                "type": "registration",
            },
        )

        # Convert options to JSON-serializable dict
        options_dict = webauthn.options_to_json(options)

        # Parse back to dict for transport
        import json

        return session_id, json.loads(options_dict)

    async def verify_registration(
        self, user: User, session_id: str, credential_json: str, name: str
    ) -> WebAuthnCredential:
        """
        Complete passkey registration.
        Verifies the attestation and stores the credential on the user.
        """
        if len(user.webauthn_credentials) >= MAX_PASSKEYS:
            raise PasskeyError(f"Cannot register more than {MAX_PASSKEYS} passkeys (maximum reached)")

        challenge_data = await self._store.get_challenge(session_id)
        if challenge_data is None:
            raise PasskeyError("Registration challenge expired or invalid")
        if challenge_data.get("type") != "registration":
            raise PasskeyError("Invalid challenge type")
        if challenge_data.get("user_id") != str(user.id):
            raise PasskeyError("Challenge does not match user")

        expected_challenge = base64url_to_bytes(challenge_data["challenge"])

        try:
            verification = webauthn.verify_registration_response(
                credential=credential_json,
                expected_challenge=expected_challenge,
                expected_rp_id=self._rp_id,
                expected_origin=self._expected_origin,
            )
        except Exception as e:
            logger.warning("passkey_registration_failed", error=str(e), user_id=str(user.id))
            raise PasskeyError("Passkey registration verification failed") from None

        new_credential = WebAuthnCredential(
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            transports=(
                [str(t.value) for t in verification.credential_device_type.transports]
                if hasattr(verification, "credential_device_type") and hasattr(verification.credential_device_type, "transports")
                else []
            ),
            name=name or "Passkey",
            aaguid=str(verification.aaguid) if verification.aaguid else "",
        )

        return new_credential

    async def generate_authentication_options(self) -> tuple[str, dict]:
        """
        Begin passkey authentication (discoverable credentials — no allowCredentials).
        Returns (session_id, options_dict) for the client.
        """
        options = webauthn.generate_authentication_options(
            rp_id=self._rp_id,
            user_verification=UserVerificationRequirement.PREFERRED,
        )

        session_id = self._store.generate_session_id()
        await self._store.store_challenge(
            session_id,
            {
                "challenge": bytes_to_base64url(options.challenge),
                "user_id": None,
                "type": "authentication",
            },
        )

        import json

        return session_id, json.loads(webauthn.options_to_json(options))

    async def verify_authentication(
        self, session_id: str, credential_json: str, credential_id_bytes: bytes, stored_credential: WebAuthnCredential
    ) -> int:
        """
        Verify passkey authentication assertion.
        Returns the new sign_count.
        """
        challenge_data = await self._store.get_challenge(session_id)
        if challenge_data is None:
            raise PasskeyError("Authentication challenge expired or invalid")
        if challenge_data.get("type") != "authentication":
            raise PasskeyError("Invalid challenge type")

        expected_challenge = base64url_to_bytes(challenge_data["challenge"])

        try:
            verification = webauthn.verify_authentication_response(
                credential=credential_json,
                expected_challenge=expected_challenge,
                expected_rp_id=self._rp_id,
                expected_origin=self._expected_origin,
                credential_public_key=stored_credential.public_key,
                credential_current_sign_count=stored_credential.sign_count,
            )
        except Exception as e:
            logger.warning("passkey_authentication_failed", error=str(e))
            raise PasskeyError("Passkey authentication verification failed") from None

        if verification.new_sign_count <= stored_credential.sign_count and stored_credential.sign_count > 0:
            logger.warning(
                "passkey_sign_count_regression",
                credential_id=bytes_to_base64url(credential_id_bytes),
                stored=stored_credential.sign_count,
                received=verification.new_sign_count,
            )

        return verification.new_sign_count
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pytest tests/unit/test_passkey_service.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/passkey_service.py backend/tests/unit/test_passkey_service.py
git commit -m "feat(auth): add PasskeyService with registration and authentication logic"
```

---

### Task 5: Passkey Schemas

**Files:**
- Modify: `backend/app/schemas/auth.py`

- [ ] **Step 1: Add passkey request/response schemas**

Add the following to `backend/app/schemas/auth.py` after the `SessionListResponse` class (after line 85):

```python


class PasskeyRegisterBeginResponse(BaseModel):
    """Response from passkey registration begin."""

    session_id: str = Field(..., description="Challenge session ID")
    options: dict = Field(..., description="PublicKeyCredentialCreationOptions")


class PasskeyRegisterCompleteRequest(BaseModel):
    """Request to complete passkey registration."""

    session_id: str = Field(..., description="Challenge session ID from begin step")
    credential: str = Field(..., description="JSON-encoded attestation response from browser")
    name: str = Field("Passkey", description="User-friendly name for this passkey", max_length=100)


class PasskeyLoginBeginResponse(BaseModel):
    """Response from passkey login begin."""

    session_id: str = Field(..., description="Challenge session ID")
    options: dict = Field(..., description="PublicKeyCredentialRequestOptions")


class PasskeyLoginCompleteRequest(BaseModel):
    """Request to complete passkey login."""

    session_id: str = Field(..., description="Challenge session ID from begin step")
    credential: str = Field(..., description="JSON-encoded assertion response from browser")


class PasskeyResponse(BaseModel):
    """A registered passkey (public info only)."""

    id: str = Field(..., description="Base64url credential ID")
    name: str = Field(..., description="User-given name")
    created_at: datetime = Field(..., description="When the passkey was registered")
    last_used_at: datetime | None = Field(None, description="Last successful authentication")
    transports: list[str] = Field(default_factory=list, description="Transport hints")


class PasskeyListResponse(BaseModel):
    """List of user's passkeys."""

    passkeys: list[PasskeyResponse]
    total: int


class PasskeyDeleteRequest(BaseModel):
    """Request to delete a passkey (requires password re-auth)."""

    password: str = Field(..., description="Current password for re-authentication")
```

- [ ] **Step 2: Verify no syntax errors**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/python -c "from app.schemas.auth import PasskeyRegisterBeginResponse, PasskeyLoginCompleteRequest, PasskeyResponse, PasskeyDeleteRequest; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/auth.py
git commit -m "feat(auth): add passkey request/response schemas"
```

---

### Task 6: Backend Passkey Endpoints

**Files:**
- Modify: `backend/app/api/v1/auth.py`
- Test: `backend/tests/unit/test_passkey_endpoints.py`

- [ ] **Step 1: Write failing integration-style test for passkey endpoints**

Create `backend/tests/unit/test_passkey_endpoints.py`:

```python
"""Tests for passkey API endpoints."""

import pytest
import pytest_asyncio

from app.models.user import User


@pytest.mark.asyncio
async def test_passkey_register_begin(client):
    """POST /auth/passkey/register/begin returns challenge options."""
    response = await client.post("/api/v1/auth/passkey/register/begin")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "options" in data
    assert "rp" in data["options"]
    assert "challenge" in data["options"]


@pytest.mark.asyncio
async def test_passkey_login_begin(client):
    """POST /auth/passkey/login/begin returns challenge options (unauthenticated)."""
    response = await client.post("/api/v1/auth/passkey/login/begin")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "options" in data
    assert "challenge" in data["options"]


@pytest.mark.asyncio
async def test_passkey_list_empty(client):
    """GET /auth/passkeys returns empty list for new user."""
    response = await client.get("/api/v1/auth/passkeys")
    assert response.status_code == 200
    data = response.json()
    assert data["passkeys"] == []
    assert data["total"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pytest tests/unit/test_passkey_endpoints.py -v
```

Expected: FAIL with 404 (routes don't exist yet).

- [ ] **Step 3: Add passkey endpoints to auth router**

Modify `backend/app/api/v1/auth.py`. Add imports at the top (after existing imports):

```python
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from app.core.redis_client import get_challenge_store
from app.services.passkey_service import PasskeyService, PasskeyError
from app.schemas.auth import (
    # ... existing imports ...
    PasskeyRegisterBeginResponse,
    PasskeyRegisterCompleteRequest,
    PasskeyLoginBeginResponse,
    PasskeyLoginCompleteRequest,
    PasskeyResponse,
    PasskeyListResponse,
    PasskeyDeleteRequest,
)
```

Add a helper to create PasskeyService instances (after the `_check_login_rate_limit` function):

```python
async def _get_passkey_service() -> PasskeyService:
    """Create a PasskeyService with the current configuration."""
    store = await get_challenge_store()
    return PasskeyService(
        challenge_store=store,
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        expected_origin=settings.webauthn_origin,
    )
```

Add the 6 endpoints at the end of `auth.py` (after the `revoke_session` endpoint):

```python
# ── Passkey / WebAuthn ──────────────────────────────────────────────────────


@router.post(
    "/auth/passkey/register/begin",
    response_model=PasskeyRegisterBeginResponse,
    tags=["Authentication"],
)
async def passkey_register_begin(current_user: User = Depends(get_current_user_from_token)):
    """Begin passkey registration — returns challenge options."""
    service = await _get_passkey_service()
    try:
        session_id, options = await service.generate_registration_options(current_user)
    except PasskeyError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None
    return PasskeyRegisterBeginResponse(session_id=session_id, options=options)


@router.post(
    "/auth/passkey/register/complete",
    response_model=PasskeyResponse,
    tags=["Authentication"],
)
async def passkey_register_complete(
    data: PasskeyRegisterCompleteRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """Complete passkey registration — verify attestation and store credential."""
    service = await _get_passkey_service()
    try:
        credential = await service.verify_registration(
            user=current_user,
            session_id=data.session_id,
            credential_json=data.credential,
            name=data.name,
        )
    except PasskeyError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None

    current_user.webauthn_credentials.append(credential)
    current_user.update_timestamp()
    await current_user.save()

    logger.info("passkey_registered", user_id=str(current_user.id), name=data.name)

    return PasskeyResponse(
        id=bytes_to_base64url(credential.credential_id),
        name=credential.name,
        created_at=credential.created_at,
        last_used_at=credential.last_used_at,
        transports=credential.transports,
    )


@router.post(
    "/auth/passkey/login/begin",
    response_model=PasskeyLoginBeginResponse,
    tags=["Authentication"],
)
async def passkey_login_begin(request: Request):
    """Begin passkey authentication — returns challenge options (no auth required)."""
    ip = request.client.host if request.client else "unknown"
    _check_login_rate_limit(f"{ip}:passkey")

    service = await _get_passkey_service()
    session_id, options = await service.generate_authentication_options()
    return PasskeyLoginBeginResponse(session_id=session_id, options=options)


@router.post(
    "/auth/passkey/login/complete",
    response_model=TokenResponse,
    tags=["Authentication"],
)
async def passkey_login_complete(request: Request, data: PasskeyLoginCompleteRequest):
    """Complete passkey authentication — verify assertion and return JWT."""
    import json as json_mod

    ip = request.client.host if request.client else "unknown"
    _check_login_rate_limit(f"{ip}:passkey")

    # Extract credential_id from the assertion to find the user
    try:
        cred_data = json_mod.loads(data.credential)
        raw_id_b64 = cred_data.get("rawId") or cred_data.get("id")
        credential_id_bytes = base64url_to_bytes(raw_id_b64)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid credential format") from exc

    # Find user by credential_id
    user = await User.find_one({"webauthn_credentials.credential_id": credential_id_bytes})
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid passkey")

    # Find the matching stored credential
    stored_cred = None
    for cred in user.webauthn_credentials:
        if cred.credential_id == credential_id_bytes:
            stored_cred = cred
            break

    if stored_cred is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid passkey")

    service = await _get_passkey_service()
    try:
        new_sign_count = await service.verify_authentication(
            session_id=data.session_id,
            credential_json=data.credential,
            credential_id_bytes=credential_id_bytes,
            stored_credential=stored_cred,
        )
    except PasskeyError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from None

    # Update credential state
    stored_cred.sign_count = new_sign_count
    stored_cred.last_used_at = datetime.now(timezone.utc)
    user.update_timestamp()
    await user.save()

    # Create JWT + session (same as password login)
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "roles": user.roles,
    }
    expires_delta = timedelta(hours=settings.access_token_expire_hours)
    access_token, token_jti = create_access_token(data=token_data, expires_delta=expires_delta)

    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")
    session = UserSession.create_session(
        user_id=user.id,
        token_jti=token_jti,
        ip_address=ip_address,
        user_agent=user_agent,
        expires_delta=expires_delta,
    )
    await session.insert()

    from app.models.system import SystemConfig

    sys_config = await SystemConfig.get_config()
    max_sessions = sys_config.max_concurrent_sessions or 5
    excess = await UserSession.find(UserSession.user_id == user.id).sort("last_activity").to_list()
    if len(excess) > max_sessions:
        for old_session in excess[: len(excess) - max_sessions]:
            await old_session.delete()

    user.update_last_login()
    await user.save()

    logger.info("user_logged_in_passkey", user_id=str(user.id), email=user.email)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=int(expires_delta.total_seconds()),
    )


@router.get(
    "/auth/passkeys",
    response_model=PasskeyListResponse,
    tags=["Authentication"],
)
async def list_passkeys(current_user: User = Depends(get_current_user_from_token)):
    """List current user's registered passkeys."""
    passkeys = [
        PasskeyResponse(
            id=bytes_to_base64url(cred.credential_id),
            name=cred.name,
            created_at=cred.created_at,
            last_used_at=cred.last_used_at,
            transports=cred.transports,
        )
        for cred in current_user.webauthn_credentials
    ]
    return PasskeyListResponse(passkeys=passkeys, total=len(passkeys))


@router.post(
    "/auth/passkey/{credential_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Authentication"],
)
async def delete_passkey(
    credential_id: str,
    data: PasskeyDeleteRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """Delete a passkey. Requires password re-authentication."""
    if not verify_password(data.password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password")

    try:
        cred_id_bytes = base64url_to_bytes(credential_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid credential ID") from exc

    original_count = len(current_user.webauthn_credentials)
    current_user.webauthn_credentials = [
        c for c in current_user.webauthn_credentials if c.credential_id != cred_id_bytes
    ]

    if len(current_user.webauthn_credentials) == original_count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passkey not found")

    current_user.update_timestamp()
    await current_user.save()

    logger.info("passkey_deleted", user_id=str(current_user.id), credential_id=credential_id)
    return None
```

Also add the missing import at the top of `auth.py`:

```python
from datetime import datetime, timedelta, timezone
```

(Replace the existing `from datetime import timedelta` import.)

- [ ] **Step 4: Add WebAuthn config fields**

Add to `backend/app/config.py` after the `device_trust_days` field (after line 43):

```python
    # WebAuthn / Passkeys
    webauthn_rp_id: str = Field(default="localhost", description="WebAuthn Relying Party ID (must match domain)")
    webauthn_rp_name: str = Field(default="Mist Automation", description="WebAuthn Relying Party display name")
    webauthn_origin: str = Field(default="http://localhost:4200", description="Expected WebAuthn origin for verification")
```

- [ ] **Step 5: Run tests**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pytest tests/unit/test_passkey_endpoints.py -v
```

Expected: All 3 tests PASS (register/begin, login/begin, list empty).

- [ ] **Step 6: Run linting**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/ruff check app/api/v1/auth.py app/services/passkey_service.py app/core/redis_client.py app/config.py && .venv/bin/black --check app/api/v1/auth.py app/services/passkey_service.py app/core/redis_client.py app/config.py
```

Fix any issues found.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/auth.py backend/app/config.py backend/tests/unit/test_passkey_endpoints.py
git commit -m "feat(auth): add passkey registration, login, and management endpoints"
```

---

### Task 7: Health Endpoint — Passkey Support Flag

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add passkey_support to health response**

In `backend/app/main.py`, in the `health_check()` function, add `passkey_support: True` to the returned dict (alongside `is_initialized`, `maintenance_mode`, etc.):

```python
        "passkey_support": True,
```

- [ ] **Step 2: Verify**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/python -c "
import asyncio
from app.main import app
print('health endpoint found:', any(r.path == '/health' for r in app.routes))
"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(auth): add passkey_support flag to health endpoint"
```

---

### Task 8: Install Frontend Dependency

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install @simplewebauthn/browser**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/frontend && npm install @simplewebauthn/browser
```

- [ ] **Step 2: Verify installation**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/frontend && node -e "const sw = require('@simplewebauthn/browser'); console.log('OK')"
```

Expected: `OK` (or ESM equivalent works).

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "feat(auth): add @simplewebauthn/browser dependency for passkey support"
```

---

### Task 9: Frontend Passkey Models

**Files:**
- Create: `frontend/src/app/core/models/passkey.model.ts`
- Modify: `frontend/src/app/core/models/session.model.ts`

- [ ] **Step 1: Create passkey model interfaces**

Create `frontend/src/app/core/models/passkey.model.ts`:

```typescript
export interface PasskeyResponse {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  transports: string[];
}

export interface PasskeyListResponse {
  passkeys: PasskeyResponse[];
  total: number;
}

export interface PasskeyRegisterBeginResponse {
  session_id: string;
  options: PublicKeyCredentialCreationOptionsJSON;
}

export interface PasskeyLoginBeginResponse {
  session_id: string;
  options: PublicKeyCredentialRequestOptionsJSON;
}
```

- [ ] **Step 2: Add passkey_support to HealthResponse**

In `frontend/src/app/core/models/session.model.ts`, add to the `HealthResponse` interface (after `password_policy`):

```typescript
  passkey_support?: boolean;
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/core/models/passkey.model.ts frontend/src/app/core/models/session.model.ts
git commit -m "feat(auth): add passkey TypeScript models and health response flag"
```

---

### Task 10: Frontend Passkey Service

**Files:**
- Create: `frontend/src/app/core/services/passkey.service.ts`

- [ ] **Step 1: Create PasskeyService**

Create `frontend/src/app/core/services/passkey.service.ts`:

```typescript
import { Injectable, inject } from '@angular/core';
import { Observable, from, switchMap, map, of } from 'rxjs';
import { startRegistration, startAuthentication } from '@simplewebauthn/browser';
import { ApiService } from './api.service';
import { TokenResponse } from '../models/user.model';
import {
  PasskeyResponse,
  PasskeyListResponse,
  PasskeyRegisterBeginResponse,
  PasskeyLoginBeginResponse,
} from '../models/passkey.model';

@Injectable({ providedIn: 'root' })
export class PasskeyService {
  private readonly api = inject(ApiService);

  isSupported(): boolean {
    return (
      typeof window !== 'undefined' &&
      typeof window.PublicKeyCredential !== 'undefined'
    );
  }

  register(name: string): Observable<PasskeyResponse> {
    return this.api
      .post<PasskeyRegisterBeginResponse>('/auth/passkey/register/begin')
      .pipe(
        switchMap((beginRes) =>
          from(startRegistration({ optionsJSON: beginRes.options })).pipe(
            switchMap((credential) =>
              this.api.post<PasskeyResponse>('/auth/passkey/register/complete', {
                session_id: beginRes.session_id,
                credential: JSON.stringify(credential),
                name,
              }),
            ),
          ),
        ),
      );
  }

  login(): Observable<TokenResponse> {
    return this.api
      .post<PasskeyLoginBeginResponse>('/auth/passkey/login/begin')
      .pipe(
        switchMap((beginRes) =>
          from(startAuthentication({ optionsJSON: beginRes.options })).pipe(
            switchMap((assertion) =>
              this.api.post<TokenResponse>('/auth/passkey/login/complete', {
                session_id: beginRes.session_id,
                credential: JSON.stringify(assertion),
              }),
            ),
          ),
        ),
      );
  }

  listPasskeys(): Observable<PasskeyListResponse> {
    return this.api.get<PasskeyListResponse>('/auth/passkeys');
  }

  deletePasskey(credentialId: string, password: string): Observable<void> {
    return this.api.post<void>(`/auth/passkey/${credentialId}/delete`, { password });
  }
}
```

- [ ] **Step 2: Verify compilation**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration development 2>&1 | head -20
```

Expected: No errors related to passkey.service.ts.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/core/services/passkey.service.ts
git commit -m "feat(auth): add PasskeyService wrapping WebAuthn browser API"
```

---

### Task 11: Login Component — Passkey Button

**Files:**
- Modify: `frontend/src/app/features/auth/login/login.component.ts`
- Modify: `frontend/src/app/features/auth/login/login.component.html`
- Modify: `frontend/src/app/features/auth/login/login.component.scss`

- [ ] **Step 1: Add passkey support to login component TypeScript**

Modify `frontend/src/app/features/auth/login/login.component.ts`:

Add imports:
```typescript
import { PasskeyService } from '../../../core/services/passkey.service';
import { TokenService } from '../../../core/services/token.service';
```

Add to the component class:
```typescript
  private readonly passkeyService = inject(PasskeyService);
  private readonly tokenService = inject(TokenService);

  passkeySupported = false;
  passkeyLoading = false;
  passkeyError: string | null = null;
```

Update `ngOnInit` to check passkey support:
```typescript
  ngOnInit(): void {
    this.passkeySupported = this.passkeyService.isSupported();
    this.authService.checkHealth().subscribe({
      next: (health) => {
        this.showOnboardLink = !health.is_initialized;
        if (!health.passkey_support) {
          this.passkeySupported = false;
        }
      },
      error: () => {},
    });
  }
```

Add passkey login method:
```typescript
  onPasskeyLogin(): void {
    this.passkeyLoading = true;
    this.passkeyError = null;
    this.passkeyService.login().subscribe({
      next: (response) => {
        this.tokenService.setToken(response.access_token, response.expires_in);
        this.store.dispatch(AuthActions.loginSuccess({ expiresIn: response.expires_in }));
        this.passkeyLoading = false;
      },
      error: (err) => {
        this.passkeyLoading = false;
        // Don't show error if user cancelled the WebAuthn prompt
        if (err?.name === 'NotAllowedError') return;
        this.passkeyError = err?.error?.detail || 'Passkey authentication failed';
      },
    });
  }
```

- [ ] **Step 2: Update login template**

Modify `frontend/src/app/features/auth/login/login.component.html`. Add the passkey button and divider between `mat-card-content` opening and the error message block. The new content section should look like:

```html
    <mat-card-content>
      @if (error$ | async; as error) {
        <div class="error-message">{{ error }}</div>
      }
      @if (passkeyError) {
        <div class="error-message">{{ passkeyError }}</div>
      }

      @if (passkeySupported) {
        <button
          mat-flat-button
          class="passkey-button"
          (click)="onPasskeyLogin()"
          [disabled]="passkeyLoading"
        >
          <mat-icon>passkey</mat-icon>
          Sign in with passkey
        </button>

        <div class="divider">
          <span>or</span>
        </div>
      }

      <form [formGroup]="loginForm" (ngSubmit)="onSubmit()">
```

(The rest of the form stays the same.)

- [ ] **Step 3: Add passkey styles**

Add to `frontend/src/app/features/auth/login/login.component.scss`:

```scss
.passkey-button {
  width: 100%;
  height: 48px;
  font-size: 16px;
  border-radius: 10px;
  gap: 8px;
}

.divider {
  display: flex;
  align-items: center;
  margin: 16px 0;

  &::before,
  &::after {
    content: '';
    flex: 1;
    border-bottom: 1px solid var(--mat-sys-outline-variant);
  }

  span {
    padding: 0 16px;
    color: var(--mat-sys-on-surface-variant);
    font-size: 14px;
  }
}
```

- [ ] **Step 4: Verify build**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration development 2>&1 | tail -5
```

Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/auth/login/
git commit -m "feat(auth): add passkey login button to login page"
```

---

### Task 12: Profile Passkeys Component

**Files:**
- Create: `frontend/src/app/features/profile/passkeys/passkeys.component.ts`
- Modify: `frontend/src/app/features/profile/profile.routes.ts`
- Modify: `frontend/src/app/features/profile/profile.component.ts`

- [ ] **Step 1: Create PasskeysComponent**

Create `frontend/src/app/features/profile/passkeys/passkeys.component.ts`:

```typescript
import { Component, inject, OnInit, signal } from '@angular/core';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { PasskeyService } from '../../../core/services/passkey.service';
import { PasskeyResponse } from '../../../core/models/passkey.model';
import { extractErrorMessage } from '../../../shared/utils/error.utils';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { ConfirmDialogComponent } from '../../../shared/components/confirm-dialog/confirm-dialog.component';

@Component({
  selector: 'app-passkeys',
  standalone: true,
  imports: [
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatDialogModule,
    DateTimePipe,
    EmptyStateComponent,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }

    <div class="passkeys-header">
      @if (passkeySupported) {
        <button mat-flat-button (click)="addPasskey()">
          <mat-icon>add</mat-icon>
          Add passkey
        </button>
      }
    </div>

    @if (!loading() && passkeys().length === 0) {
      <app-empty-state
        icon="passkey"
        title="No passkeys registered"
        subtitle="Add a passkey for faster, passwordless sign-in."
      ></app-empty-state>
    } @else if (passkeys().length > 0) {
      <div class="table-container">
        <table mat-table [dataSource]="passkeys()">
          <ng-container matColumnDef="name">
            <th mat-header-cell *matHeaderCellDef>Name</th>
            <td mat-cell *matCellDef="let p">
              <mat-icon class="passkey-icon">passkey</mat-icon>
              {{ p.name }}
            </td>
          </ng-container>

          <ng-container matColumnDef="created_at">
            <th mat-header-cell *matHeaderCellDef>Registered</th>
            <td mat-cell *matCellDef="let p">{{ p.created_at | dateTime }}</td>
          </ng-container>

          <ng-container matColumnDef="last_used_at">
            <th mat-header-cell *matHeaderCellDef>Last Used</th>
            <td mat-cell *matCellDef="let p">
              {{ p.last_used_at ? (p.last_used_at | dateTime) : 'Never' }}
            </td>
          </ng-container>

          <ng-container matColumnDef="actions">
            <th mat-header-cell *matHeaderCellDef></th>
            <td mat-cell *matCellDef="let p">
              <button mat-stroked-button color="warn" (click)="deletePasskey(p)">Remove</button>
            </td>
          </ng-container>

          <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
          <tr mat-row *matRowDef="let row; columns: displayedColumns"></tr>
        </table>
      </div>
    }
  `,
  styles: [
    \`
      .passkeys-header {
        display: flex;
        justify-content: flex-end;
        margin-bottom: 16px;
      }
      .table-container {
        overflow-x: auto;
      }
      table {
        width: 100%;
      }
      .passkey-icon {
        vertical-align: middle;
        margin-right: 8px;
        font-size: 20px;
        height: 20px;
        width: 20px;
      }
    \`,
  ],
})
export class PasskeysComponent implements OnInit {
  private readonly passkeyService = inject(PasskeyService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);

  passkeys = signal<PasskeyResponse[]>([]);
  loading = signal(true);
  passkeySupported = false;
  displayedColumns = ['name', 'created_at', 'last_used_at', 'actions'];

  ngOnInit(): void {
    this.passkeySupported = this.passkeyService.isSupported();
    this.loadPasskeys();
  }

  loadPasskeys(): void {
    this.loading.set(true);
    this.passkeyService.listPasskeys().subscribe({
      next: (res) => {
        this.passkeys.set(res.passkeys);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  addPasskey(): void {
    const name = prompt('Enter a name for this passkey (e.g., "MacBook Touch ID"):');
    if (!name) return;

    this.passkeyService.register(name).subscribe({
      next: () => {
        this.snackBar.open('Passkey registered', 'OK', { duration: 3000 });
        this.loadPasskeys();
      },
      error: (err) => {
        if (err?.name === 'NotAllowedError') return;
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  deletePasskey(passkey: PasskeyResponse): void {
    const password = prompt('Enter your password to confirm removal:');
    if (!password) return;

    this.passkeyService.deletePasskey(passkey.id, password).subscribe({
      next: () => {
        this.snackBar.open('Passkey removed', 'OK', { duration: 3000 });
        this.loadPasskeys();
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }
}
```

- [ ] **Step 2: Add route to profile**

Modify `frontend/src/app/features/profile/profile.routes.ts`. Add after the `sessions` route (after line 23):

```typescript
      {
        path: 'passkeys',
        loadComponent: () =>
          import('./passkeys/passkeys.component').then((m) => m.PasskeysComponent),
      },
```

- [ ] **Step 3: Add tab to profile navigation**

Modify `frontend/src/app/features/profile/profile.component.ts`. Add a new tab link after the "Sessions" tab (after line 35):

```html
      <a
        mat-tab-link
        routerLink="passkeys"
        routerLinkActive
        #pk="routerLinkActive"
        [active]="pk.isActive"
        >Passkeys</a
      >
```

- [ ] **Step 4: Verify build**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration development 2>&1 | tail -5
```

Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/profile/passkeys/ frontend/src/app/features/profile/profile.routes.ts frontend/src/app/features/profile/profile.component.ts
git commit -m "feat(auth): add passkey management page in profile settings"
```

---

### Task 13: UserResponse — has_passkeys Field

**Files:**
- Modify: `backend/app/schemas/auth.py`
- Modify: `backend/app/schemas/user.py` (or wherever `user_to_response` builds UserResponse)
- Modify: `frontend/src/app/core/models/user.model.ts`

This field lets the frontend know if a user has passkeys registered (useful for future conditional UI).

- [ ] **Step 1: Add has_passkeys to UserResponse**

In `backend/app/schemas/auth.py`, add to `UserResponse` (after `totp_enabled` on line 36):

```python
    has_passkeys: bool = Field(default=False, description="Whether user has registered passkeys")
```

- [ ] **Step 2: Update user_to_response helper**

Find where `user_to_response()` is defined (likely `backend/app/schemas/user.py`) and add:

```python
    has_passkeys=len(user.webauthn_credentials) > 0,
```

- [ ] **Step 3: Update frontend UserResponse interface**

In `frontend/src/app/core/models/user.model.ts`, add to `UserResponse` (after `totp_enabled`):

```typescript
  has_passkeys: boolean;
```

- [ ] **Step 4: Verify build (both)**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/python -c "from app.schemas.auth import UserResponse; print('OK')"
cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration development 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/auth.py backend/app/schemas/user.py frontend/src/app/core/models/user.model.ts
git commit -m "feat(auth): add has_passkeys field to UserResponse"
```

---

### Task 14: Full Integration Test

**Files:**
- Modify: `backend/tests/unit/test_passkey_endpoints.py`

- [ ] **Step 1: Run all existing tests to check for regressions**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pytest tests/ -v --timeout=30 2>&1 | tail -30
```

Expected: All existing tests pass. Fix any regressions.

- [ ] **Step 2: Run frontend build**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration development
```

Expected: Build succeeds with no errors.

- [ ] **Step 3: Run linting on all changed files**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/ruff check app/ && .venv/bin/black --check app/
```

Fix any issues.

- [ ] **Step 4: Run frontend lint**

Run:
```bash
cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng lint 2>&1 | tail -10
```

Fix any issues.

- [ ] **Step 5: Final commit if fixes were needed**

```bash
git add -A
git commit -m "fix(auth): fix lint and test issues in passkey implementation"
```

---

### Task 15: Verify & Run

- [ ] **Step 1: Run all backend tests**

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/pytest tests/ -v --timeout=30
```

Expected: All tests pass.

- [ ] **Step 2: Run frontend build**

```bash
cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build
```

Expected: Build succeeds.
