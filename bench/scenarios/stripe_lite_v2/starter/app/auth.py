"""Trivial bearer-token auth — `Bearer user:<id>` or `Bearer admin:<id>`."""
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from .db import get_db
from .models import User


def current_user(authorization: str = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    parts = token.split(":")
    if len(parts) != 2 or parts[0] not in ("user", "admin"):
        raise HTTPException(status_code=401, detail="bad token format")
    try:
        user_id = int(parts[1])
    except ValueError:
        raise HTTPException(status_code=401, detail="bad user id in token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="unknown user")
    if parts[0] == "admin" and not user.is_admin:
        raise HTTPException(status_code=403, detail="admin required")
    return user


def admin_only(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin required")
    return user
