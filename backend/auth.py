import secrets

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, func, select

from backend.db import get_session
from backend.models import Invite, User, utcnow


class RegistrationError(Exception):
    pass


def current_user(
    request: Request, session: Session = Depends(get_session)
) -> User:
    user = session.get(User, request.session.get("user_id"))
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def reset_password(session: Session, email: str, new_password: str) -> User | None:
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        return None
    user.hashed_password = hash_password(new_password)
    session.add(user)
    session.commit()
    return user


def generate_invite(session: Session, creator: User) -> Invite:
    invite = Invite(
        code=secrets.token_urlsafe(8),
        created_by_user_id=creator.id,
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return invite


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def register_user(
    session: Session,
    email: str,
    password: str,
    invite_code: str | None = None,
) -> User:
    # The first account ever created bootstraps the Admin (see ADR-0004:
    # invite-only registration needs at least one invite-generating user).
    no_users_yet = session.exec(select(func.count()).select_from(User)).one() == 0

    invite = None
    if not no_users_yet:
        invite = session.exec(
            select(Invite).where(Invite.code == invite_code)
        ).first() if invite_code else None
        if invite is None or invite.used_by_user_id is not None:
            raise RegistrationError("A valid, unused invite code is required.")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        is_admin=no_users_yet,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    if invite is not None:
        invite.used_by_user_id = user.id
        invite.used_at = utcnow()
        session.add(invite)
        session.commit()

    return user
