import base64
import json
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ..config import Settings, get_settings
from ..database import get_db
from ..dependencies import CurrentUser
from ..models import AuditLog, User, WebAuthnCredential
from ..schemas import Envelope, LoginRequest
from ..security import create_session_token, hash_ip, new_csrf_token, verify_password
from ..serialization import model_dict

router = APIRouter(prefix="/auth", tags=["authentication"])


class PasskeyRegistrationComplete(BaseModel):
    challenge_id: str = Field(min_length=20, max_length=200)
    credential: dict[str, Any]
    name: str = Field(default="Passkey", min_length=1, max_length=200)


class PasskeyLoginBegin(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasskeyLoginComplete(BaseModel):
    challenge_id: str = Field(min_length=20, max_length=200)
    credential: dict[str, Any]


def challenge_store(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=1,
        socket_timeout=1,
        decode_responses=True,
    )


def save_challenge(settings: Settings, kind: str, user_id: str, challenge: bytes) -> str:
    challenge_id = secrets.token_urlsafe(32)
    value = json.dumps(
        {
            "kind": kind,
            "user_id": user_id,
            "challenge": base64.urlsafe_b64encode(challenge).decode("ascii"),
        }
    )
    try:
        challenge_store(settings).setex(f"webauthn:{challenge_id}", 300, value)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="passkey challenge store unavailable") from exc
    return challenge_id


def consume_challenge(settings: Settings, challenge_id: str, kind: str) -> dict[str, str]:
    store = challenge_store(settings)
    key = f"webauthn:{challenge_id}"
    try:
        raw = store.getdel(key)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="passkey challenge store unavailable") from exc
    if not isinstance(raw, str) or not raw:
        raise HTTPException(status_code=400, detail="passkey challenge expired or already used")
    parsed = json.loads(raw)
    if parsed.get("kind") != kind:
        raise HTTPException(status_code=400, detail="passkey challenge purpose mismatch")
    return {str(key): str(value) for key, value in parsed.items()}


@router.post("/login", response_model=Envelope[dict[str, object]])
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Envelope[dict[str, object]]:
    email = payload.email.strip().lower()
    if email not in settings.account_allowlist:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account is not allowlisted")
    user = db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is None or user.disabled or not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    user.last_login_at = datetime.now(UTC)
    csrf = new_csrf_token()
    response.set_cookie(
        "signal_session",
        create_session_token(user.id, settings),
        httponly=True,
        secure=settings.production,
        samesite="strict",
        max_age=86_400,
        path="/",
    )
    response.set_cookie(
        "signal_csrf",
        csrf,
        httponly=False,
        secure=settings.production,
        samesite="strict",
        max_age=86_400,
        path="/",
    )
    db.add(
        AuditLog(
            user_id=user.id,
            action="LOGIN",
            request_id=request.headers.get("x-request-id"),
            ip_hash=hash_ip(
                request.client.host if request.client else None,
                settings.SESSION_SECRET.get_secret_value(),
            ),
        )
    )
    db.commit()
    return Envelope(data={"user": model_dict(user), "csrf_token": csrf})


@router.post("/logout", response_model=Envelope[dict[str, bool]])
def logout(response: Response, _user: CurrentUser) -> Envelope[dict[str, bool]]:
    response.delete_cookie("signal_session", path="/")
    response.delete_cookie("signal_csrf", path="/")
    return Envelope(data={"logged_out": True})


@router.post("/passkeys/register/options", response_model=Envelope[dict[str, Any]])
def passkey_registration_options(
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    existing = list(
        db.scalars(
            select(WebAuthnCredential).where(
                WebAuthnCredential.user_id == user.id,
                WebAuthnCredential.deleted_at.is_(None),
            )
        )
    )
    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=user.id.encode("utf-8"),
        user_name=user.email,
        user_display_name=user.display_name or user.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(row.credential_id))
            for row in existing
        ],
    )
    challenge_id = save_challenge(settings, "registration", user.id, options.challenge)
    return Envelope(
        data={"challenge_id": challenge_id, "public_key": json.loads(options_to_json(options))}
    )


@router.post("/passkeys/register/complete", response_model=Envelope[dict[str, Any]])
def passkey_registration_complete(
    payload: PasskeyRegistrationComplete,
    user: CurrentUser,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    challenge = consume_challenge(settings, payload.challenge_id, "registration")
    if challenge["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="passkey challenge belongs to another user")
    try:
        verified = verify_registration_response(
            credential=payload.credential,
            expected_challenge=base64.urlsafe_b64decode(challenge["challenge"]),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            require_user_verification=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="passkey registration verification failed") from exc
    credential_id = bytes_to_base64url(verified.credential_id)
    if db.scalar(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == credential_id
        )
    ):
        raise HTTPException(status_code=409, detail="passkey is already registered")
    item = WebAuthnCredential(
        user_id=user.id,
        credential_id=credential_id,
        public_key=base64.urlsafe_b64encode(verified.credential_public_key).decode("ascii"),
        sign_count=verified.sign_count,
        transports=[
            str(value)
            for value in payload.credential.get("response", {}).get("transports", [])
        ],
        name=payload.name,
    )
    db.add(item)
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action="PASSKEY_REGISTERED",
            target_type="WEBAUTHN_CREDENTIAL",
            target_id=item.id,
        )
    )
    db.commit()
    return Envelope(data={"id": item.id, "name": item.name})


@router.post("/passkeys/login/options", response_model=Envelope[dict[str, Any]])
def passkey_login_options(
    payload: PasskeyLoginBegin,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    email = payload.email.strip().lower()
    if email not in settings.account_allowlist:
        raise HTTPException(status_code=403, detail="account is not allowlisted")
    user = db.scalar(
        select(User).where(User.email == email, User.disabled.is_(False), User.deleted_at.is_(None))
    )
    if user is None:
        raise HTTPException(status_code=404, detail="passkey account not found")
    credentials = list(
        db.scalars(
            select(WebAuthnCredential).where(
                WebAuthnCredential.user_id == user.id,
                WebAuthnCredential.deleted_at.is_(None),
            )
        )
    )
    if not credentials:
        raise HTTPException(status_code=404, detail="no passkeys are registered")
    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(row.credential_id))
            for row in credentials
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    challenge_id = save_challenge(settings, "authentication", user.id, options.challenge)
    return Envelope(
        data={"challenge_id": challenge_id, "public_key": json.loads(options_to_json(options))}
    )


@router.post("/passkeys/login/complete", response_model=Envelope[dict[str, Any]])
def passkey_login_complete(
    payload: PasskeyLoginComplete,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> Envelope[dict[str, Any]]:
    challenge = consume_challenge(settings, payload.challenge_id, "authentication")
    user = db.get(User, challenge["user_id"])
    if user is None or user.disabled or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="account unavailable")
    credential_id = str(payload.credential.get("id", ""))
    credential = db.scalar(
        select(WebAuthnCredential).where(
            WebAuthnCredential.user_id == user.id,
            WebAuthnCredential.credential_id == credential_id,
            WebAuthnCredential.deleted_at.is_(None),
        )
    )
    if credential is None:
        raise HTTPException(status_code=401, detail="passkey credential is not registered")
    try:
        verified = verify_authentication_response(
            credential=payload.credential,
            expected_challenge=base64.urlsafe_b64decode(challenge["challenge"]),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=base64.urlsafe_b64decode(credential.public_key),
            credential_current_sign_count=credential.sign_count,
            require_user_verification=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="passkey authentication failed") from exc
    credential.sign_count = verified.new_sign_count
    credential.last_used_at = datetime.now(UTC)
    user.last_login_at = datetime.now(UTC)
    csrf = new_csrf_token()
    response.set_cookie(
        "signal_session",
        create_session_token(user.id, settings),
        httponly=True,
        secure=settings.production,
        samesite="strict",
        max_age=86_400,
        path="/",
    )
    response.set_cookie(
        "signal_csrf",
        csrf,
        httponly=False,
        secure=settings.production,
        samesite="strict",
        max_age=86_400,
        path="/",
    )
    db.add(
        AuditLog(
            user_id=user.id,
            action="PASSKEY_LOGIN",
            target_type="WEBAUTHN_CREDENTIAL",
            target_id=credential.id,
            request_id=request.headers.get("x-request-id"),
        )
    )
    db.commit()
    return Envelope(data={"user": model_dict(user), "csrf_token": csrf})
