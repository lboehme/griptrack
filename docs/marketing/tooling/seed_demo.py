"""Seed a believable demo account for the marketing screenshots and video.

Builds ~16 weeks of block-pull training for one on-device user ("Alex"):
monthly max tests on half crimp / 20 mm (plus a few open-hand and pinch
tests), 2-3 sessions a week of 3 x 5 work sets per hand with RPE, one
deload week, boulder sends climbing from 6B to 7A+, and a weekly
bodyweight log. Everything is written straight through the SQLModel
models against an already-migrated SQLite file, so the app renders it
exactly as it would real data.

Usage (from the repo root):
    GRIPTRACK_DATABASE_URL=sqlite:///path/to/demo.db alembic upgrade head
    GRIPTRACK_DATABASE_URL=sqlite:///path/to/demo.db \
        python docs/marketing/tooling/seed_demo.py --today 2026-09-26
"""

import argparse
import math
import random
from datetime import date, datetime, time, timedelta, timezone

from sqlmodel import Session, select

from backend import auth, plates
from backend.db import engine
from backend.models import (
    BodyWeightLog,
    Climb,
    GripType,
    MaxWeightTest,
    PlateInventoryItem,
    TrainingSession,
    WorkSet,
)

HALF_CRIMP_EDGE = 20
DEMO_PLATES = [(20.0, 2), (10.0, 2), (5.0, 2), (2.5, 2), (1.0, 2), (0.5, 2)]

# (days before today, left kg, right kg) -- the headline combo's tests.
HALF_CRIMP_TESTS = [
    (116, 36.0, 38.0),
    (81, 38.5, 40.0),
    (46, 41.0, 42.5),
    (11, 44.0, 45.0),
]
OPEN_HAND_TESTS = [(68, 29.5, 31.0), (18, 32.5, 33.5)]
PINCH_TESTS = [(53, 24.0, 25.5)]

# Font grades a climber moving from 6B to 7A+ would log, per 4-week block.
GRADE_BANDS = [
    ["6A+", "6B", "6B", "6B+", "6B+", "6C"],
    ["6B", "6B+", "6B+", "6C", "6C", "6C+"],
    ["6B+", "6C", "6C+", "6C+", "7A", "7A"],
    ["6C", "6C+", "7A", "7A", "7A+", "7A+"],
]


def utc(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.utc)


def seed(today: date) -> None:
    rng = random.Random(7)
    with Session(engine) as session:
        user = auth.create_device_user(session, name="Alex", unit_pref="kg", hand_order_pref="alternating")
        # A typical home block-pull kit, replacing the generic starter set.
        for item in plates.inventory_for(session, user):
            session.delete(item)
        for weight, count in DEMO_PLATES:
            session.add(PlateInventoryItem(user_id=user.id, weight=weight, count=count))
        session.commit()

        def loadable(target: float) -> float:
            # Whole or half kilos: what people actually load.
            return math.floor(target * 2) / 2

        grips = {g.name: g for g in session.exec(select(GripType)).all()}
        half_crimp = grips["half crimp"]
        open_hand = grips["open hand"]
        pinch = grips["pinch"]

        for tests, grip, edge in (
            (HALF_CRIMP_TESTS, half_crimp, HALF_CRIMP_EDGE),
            (OPEN_HAND_TESTS, open_hand, 15),
            (PINCH_TESTS, pinch, 40),
        ):
            for days_ago, left, right in tests:
                for hand, weight in (("left", left), ("right", right)):
                    session.add(
                        MaxWeightTest(
                            user_id=user.id,
                            hand=hand,
                            grip_type_id=grip.id,
                            edge_mm=edge,
                            date=today - timedelta(days=days_ago),
                            weight=weight,
                        )
                    )

        # Bodyweight: weekly, a slow cut from 70.4 to ~68.6 kg.
        start = today - timedelta(days=119)
        for week in range(18):
            day = start + timedelta(days=7 * week)
            if day > today - timedelta(days=2):
                break
            weight = 70.4 - 0.11 * week + rng.choice([-0.2, -0.1, 0.0, 0.1, 0.2])
            session.add(BodyWeightLog(user_id=user.id, date=day, weight=round(weight, 1)))

        # Training: Mon/Wed/Fri-ish pull days (last one two days ago, so Today
        # offers a fresh plan), with the occasional skipped day.
        deload_start = today - timedelta(days=40)
        deload_end = deload_start + timedelta(days=6)
        day = today - timedelta(days=115)
        last_pull = today - timedelta(days=2)
        pull_days: list[date] = []
        while day <= last_pull:
            if day.weekday() in (0, 3) or (day.weekday() == 5 and rng.random() < 0.45):
                pull_days.append(day)
            day += timedelta(days=1)
        if last_pull not in pull_days:
            pull_days.append(last_pull)

        def current_test(hand: str, on: date) -> float:
            best = HALF_CRIMP_TESTS[0][1 if hand == "left" else 2]
            for days_ago, left, right in HALF_CRIMP_TESTS:
                if today - timedelta(days=days_ago) <= on:
                    best = left if hand == "left" else right
            return best

        for index, day in enumerate(pull_days):
            deload = deload_start <= day <= deload_end
            recent = day >= today - timedelta(days=9)
            ts = TrainingSession(
                user_id=user.id,
                date=day,
                session_number=1,
                is_deload=deload,
                started_at=utc(day, 17, rng.choice([5, 20, 35, 50])),
                notes=(
                    "Deload week, kept it crisp."
                    if deload
                    else "Felt snappy, left hand caught up."
                    if day == last_pull
                    else None
                ),
            )
            minutes = rng.randint(34, 48)
            ts.finished_at = ts.started_at + timedelta(minutes=minutes)  # type: ignore[operator]
            ts.session_rpe = 5 if deload else (6 if recent else rng.choice([7, 7, 8, 8, 9]))
            session.add(ts)
            session.flush()
            # Weeks since the last test: intensity creeps from ~78 % to ~84 %.
            for hand in ("left", "right"):
                test = current_test(hand, day)
                pct = 0.62 if deload else 0.78 + 0.02 * min(index % 6, 3)
                weight = loadable(test * pct)
                for set_number in (1, 2, 3):
                    if recent:
                        rpe = 7.0
                    elif deload:
                        rpe = 5.5
                    else:
                        rpe = rng.choice([7.0, 7.5, 8.0, 8.0, 8.5]) + 0.5 * (set_number - 1)
                    session.add(
                        WorkSet(
                            training_session_id=ts.id,
                            hand=hand,
                            grip_type_id=half_crimp.id,
                            edge_mm=HALF_CRIMP_EDGE,
                            weight=weight,
                            reps=5,
                            set_number=set_number,
                            rpe=min(rpe, 9.5),
                        )
                    )

        # Climbing: two gym days a week, 2-4 logged problems each.
        day = today - timedelta(days=114)
        while day < today:
            if day.weekday() in (1, 5) and day != today - timedelta(days=1):
                block = min((today - day).days, 111)
                band = GRADE_BANDS[3 - block // 28]
                for _ in range(rng.randint(2, 4)):
                    grade = rng.choice(band)
                    style = rng.choices(["flash", "redpoint", "attempt"], weights=[4, 5, 2])[0]
                    session.add(
                        Climb(
                            user_id=user.id,
                            date=day,
                            discipline="boulder",
                            grade=grade,
                            style=style,
                        )
                    )
            day += timedelta(days=1)
        # Something to brag about on the timeline.
        session.add(
            Climb(
                user_id=user.id,
                date=today - timedelta(days=3),
                discipline="boulder",
                grade="7A+",
                style="redpoint",
                notes="The crimpy arete. Finally.",
            )
        )
        session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    seed(parser.parse_args().today)
