import os

from sqlmodel import Session, create_engine

# Support GRIPTRACK_DATABASE_URL (as documented) or fall back to DATABASE_URL / default sqlite file.
DATABASE_URL = os.environ.get("GRIPTRACK_DATABASE_URL") or os.environ.get("DATABASE_URL", "sqlite:///./griptrack.db")

# Automatically create the parent directory if it's a local SQLite file database and doesn't exist yet
if DATABASE_URL.startswith("sqlite:///"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    # For sqlite:////absolute/path (starts with / after replacing sqlite:///)
    # and sqlite:///relative/path
    if db_path and db_path != ":memory:":
        from pathlib import Path
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def get_session():
    with Session(engine) as session:
        yield session
