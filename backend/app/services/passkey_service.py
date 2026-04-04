"""
Passkey (WebAuthn) service for registration and authentication.
"""

from __future__ import annotations

import structlog
import webauthn
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
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
        """Begin passkey registration. Returns (session_id, options_dict)."""
        if len(user.webauthn_credentials) >= MAX_PASSKEYS:
            raise PasskeyError(f"Cannot register more than {MAX_PASSKEYS} passkeys (maximum reached)")

        exclude_credentials = [
            PublicKeyCredentialDescriptor(
                id=cred.credential_id,
                transports=[AuthenticatorTransport(t) for t in cred.transports if t],
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

        import json
        return session_id, json.loads(webauthn.options_to_json(options))

    async def verify_registration(
        self, user: User, session_id: str, credential_json: str, name: str
    ) -> WebAuthnCredential:
        """Complete passkey registration. Verify attestation, return credential."""
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
            name=name or "Passkey",
            aaguid=str(verification.aaguid) if verification.aaguid else "",
        )

        return new_credential

    async def generate_authentication_options(self) -> tuple[str, dict]:
        """Begin passkey authentication (discoverable). Returns (session_id, options_dict)."""
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
        """Verify passkey authentication assertion. Returns new sign_count."""
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
