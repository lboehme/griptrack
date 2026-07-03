from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    is_admin: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Invite(SQLModel, table=True):
    __tablename__ = "invites"

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    created_by_user_id: int = Field(foreign_key="users.id")
    used_by_user_id: int | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)
    used_at: datetime | None = None
