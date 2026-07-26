from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..dependencies import CurrentUser
from ..models import AuditLog, User
from ..schemas import Envelope, LoginRequest
from ..security import create_session_token, hash_ip, new_csrf_token, verify_password
from ..serialization import model_dict

router = APIRouter(prefix="/auth", tags=["authentication"])


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
