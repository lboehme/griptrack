import base64
import hashlib
import hmac
import os
import secrets
import time

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, func, select

from backend.db import get_session
from backend.models import VALID_UNITS, Invite, User, utcnow
from backend.plates import seed_default_inventory

PASSWORD_MIN_LENGTH = 8
# PBKDF2 hashes the whole input (no bcrypt 72-byte truncation), so this is just
# DoS hygiene / sanity, not a correctness limit — generous enough for any real
# passphrase.
PASSWORD_MAX_BYTES = 1024

# Password hashing is stdlib PBKDF2-HMAC-SHA256 rather than bcrypt/argon2/scrypt:
# those are native (Rust/C) wheels, and the on-device Android target (PRD #93)
# wants to minimise the native-wheel surface — see docs/adr/0009 and #108.
# PBKDF2 is a NIST-approved KDF; weaker per-iteration than bcrypt against GPU
# attackers, but acceptable for a personal, invite-only, rate-limited instrument
# (ADR-0006). The iteration count is stored in each hash, so it can be raised
# later without invalidating existing hashes. 600k is OWASP's 2023 floor for
# PBKDF2-HMAC-SHA256.
_PBKDF2_ALGORITHM = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_SALT_BYTES = 16

LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_SECONDS = 60.0


class RegistrationError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, _PBKDF2_ITERATIONS
    )
    salt_b64 = base64.b64encode(salt).decode()
    hash_b64 = base64.b64encode(derived).decode()
    return f"{_PBKDF2_ALGORITHM}${_PBKDF2_ITERATIONS}${salt_b64}${hash_b64}"


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time check against a stored ``pbkdf2_sha256$…`` hash.

    Fails closed (returns False, never raises) on any malformed or legacy
    (e.g. bcrypt ``$2b$…``) hash — those accounts must be reset, see #108.
    """
    try:
        algorithm, iterations_s, salt_b64, hash_b64 = hashed.split("$")
        iterations = int(iterations_s)
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(hash_b64, validate=True)
    except (ValueError, TypeError):
        return False
    if algorithm != _PBKDF2_ALGORITHM or iterations < 1 or not expected:
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, iterations, dklen=len(expected)
    )
    return hmac.compare_digest(derived, expected)


# Precomputed so authenticate() can spend the same hashing time whether or not
# the email exists (no user-enumeration via response timing).
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class LoginRateLimiter:
    """Sliding-window failed-login limiter, keyed by client address.

    In-memory and per-process — right-sized for a single-instance
    deployment; a horizontally scaled setup would need shared state.
    """

    def __init__(self, max_failures=LOGIN_MAX_FAILURES, window=LOGIN_WINDOW_SECONDS):
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, list[float]] = {}

    def blocked(self, key: str) -> bool:
        cutoff = time.monotonic() - self.window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        self._failures[key] = recent
        return len(recent) >= self.max_failures

    def record_failure(self, key: str) -> None:
        self._failures.setdefault(key, []).append(time.monotonic())


def current_user(
    request: Request, session: Session = Depends(get_session)
) -> User:
    user = session.get(User, request.session.get("user_id"))
    if user is None or request.session.get("session_version") != user.session_version:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        verify_password(password, _DUMMY_HASH)  # equalize timing
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def reset_password(session: Session, email: str, new_password: str) -> User | None:
    validate_password(new_password)
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        return None
    user.hashed_password = hash_password(new_password)
    user.session_version += 1
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


def validate_password(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise RegistrationError(
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
        )
    if len(password.encode()) > PASSWORD_MAX_BYTES:
        raise RegistrationError("Password is too long.")


def normalize_name(name: str | None) -> str | None:
    """Trimmed display name; blank collapses to None (no name set)."""
    if name is None:
        return None
    name = name.strip()
    return name or None


def register_user(
    session: Session,
    email: str,
    password: str,
    invite_code: str | None = None,
    unit_pref: str = "kg",
    name: str | None = None,
) -> User:
    email = email.strip().lower()
    validate_password(password)
    if unit_pref not in VALID_UNITS:
        raise RegistrationError("Unit must be kg or lbs.")

    # The first account ever created bootstraps the Admin (see ADR-0004:
    # invite-only registration needs at least one invite-generating user).
    no_users_yet = session.exec(select(func.count()).select_from(User)).one() == 0

    invite = None
    if no_users_yet:
        # When GRIPTRACK_BOOTSTRAP_TOKEN is set (recommended for public
        # deploys), the very first registration must present it — closing the
        # window where a stranger could claim admin before the owner registers.
        bootstrap_token = os.environ.get("GRIPTRACK_BOOTSTRAP_TOKEN")
        if bootstrap_token and invite_code != bootstrap_token:
            raise RegistrationError("A valid bootstrap token is required.")
    else:
        invite = session.exec(
            select(Invite).where(Invite.code == invite_code)
        ).first() if invite_code else None
        if invite is None or invite.used_by_user_id is not None:
            raise RegistrationError("A valid, unused invite code is required.")

    if session.exec(select(User).where(User.email == email)).first() is not None:
        raise RegistrationError("That email is already registered.")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        name=normalize_name(name),
        is_admin=no_users_yet,
        unit_pref=unit_pref,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    if invite is not None:
        invite.used_by_user_id = user.id
        invite.used_at = utcnow()
        session.add(invite)
        session.commit()

    seed_default_inventory(session, user)

    return user
