import secrets
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db
from .models import User
from .secrets_store import resolved_secret
from .security import decode_session_token, require_csrf

DB = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


def current_user(
    request: Request,
    db: DB,
    settings: Config,
    signal_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    user_id: str | None = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        tool_api_key = resolved_secret(
            db,
            settings,
            "tool_api.key",
            settings.TOOL_API_KEY.get_secret_value(),
        )
        if secrets.compare_digest(token, tool_api_key):
            user = db.query(User).filter(User.disabled.is_(False), User.deleted_at.is_(None)).first()
            if user is None:
                raise HTTPException(status_code=503, detail="initial user is not configured")
            return user
    if signal_session:
        user_id = decode_session_token(signal_session, settings)
        require_csrf(request)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    user = db.get(User, user_id)
    if user is None or user.disabled or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account unavailable")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
