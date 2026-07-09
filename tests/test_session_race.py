"""backend.training_log.start_or_get_session's auto-increment race
(Opus review of PR #63): two concurrent first-POSTs on the same (user,
date) can both read "no session yet" and both compute next_number=1 —
the loser then hits the (user_id, date, session_number) unique
constraint on commit.

This is a direct module-level test rather than the usual HTTP seam (see
CLAUDE.md's HTTP-seam testing decision) because reproducing a genuine
race needs to inject a commit between start_or_get_session's read and its
own write — not observable from outside the module."""

from datetime import date as date_type

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend import training_log
from backend.models import TrainingSession, User


def make_session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_concurrent_first_posts_dont_500_on_the_unique_constraint(monkeypatch):
    session = make_session()
    user = User(email="racer@example.com", hashed_password="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    date = date_type(2026, 7, 4)

    def stale_latest_session_number(session_arg, user_arg, date_arg):
        # Simulate the concurrent winner: its session commits in the gap
        # between our find_session() read and our own insert attempt, but
        # our own (now-stale) read still reports nothing exists yet — this
        # matters for offline-sync replay too (#20), where retried writes
        # after a reconnect can race the same way.
        winner = TrainingSession(user_id=user.id, date=date, session_number=1)
        session_arg.add(winner)
        session_arg.commit()
        return None

    monkeypatch.setattr(
        training_log, "latest_session_number", stale_latest_session_number
    )

    result = training_log.start_or_get_session(session, user, date)

    assert result.session_number == 1
    assert result.id is not None
    rows = session.exec(
        select(TrainingSession).where(TrainingSession.date == date)
    ).all()
    assert len(rows) == 1
