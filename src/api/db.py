"""
Database setup — SQLAlchemy 2.0 + SQLite.

The database file lives at db/call_quality.db (relative to the project root,
which is two levels above this file: src/api/db.py → project root).

Call init_db() once at app startup to create all tables. Use get_db() as a
FastAPI dependency to obtain a per-request Session that is automatically
closed when the request finishes.

For background tasks (which run outside the request/response cycle), create
a session directly via new_session() and manage its lifecycle manually.
"""

from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Resolve project root from this file's location (src/api/db.py → ../../)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DB_DIR = _PROJECT_ROOT / "db"
_DB_PATH = _DB_DIR / "call_quality.db"


def _ensure_db_dir() -> None:
    _DB_DIR.mkdir(parents=True, exist_ok=True)


_ensure_db_dir()

# connect_args check_same_thread=False is required for SQLite when the same
# connection is used from multiple threads (e.g. FastAPI BackgroundTasks).
engine = create_engine(
    f"sqlite:///{_DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def _run_migrations(conn) -> None:
    """
    Apply additive schema changes that create_all() cannot handle (new columns
    on existing tables). Each migration is idempotent — safe to run on every
    startup.
    """
    # Fetch current columns for each table via SQLite's PRAGMA.
    def columns(table: str) -> set[str]:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return {row[1] for row in rows}

    stt_cols = columns("stt_jobs")
    if "gcs_uri" not in stt_cols:
        conn.execute(text("ALTER TABLE stt_jobs ADD COLUMN gcs_uri TEXT"))

    pipeline_cols = columns("pipeline_jobs")
    if "sales_rep_name" not in pipeline_cols:
        conn.execute(text("ALTER TABLE pipeline_jobs ADD COLUMN sales_rep_name TEXT"))


def init_db() -> None:
    """Create all tables defined on Base, then apply additive migrations."""
    # Import models here so SQLAlchemy registers them on Base before create_all.
    from src.api.models import jobs  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Run column-level migrations that create_all() skips.
    with engine.connect() as conn:
        _run_migrations(conn)
        conn.commit()


def get_db():
    """
    FastAPI dependency that yields a SQLAlchemy Session and closes it after
    the request, even if an exception is raised.

    Usage:
        @router.get("/foo")
        def foo(db: Session = Depends(get_db)):
            ...
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def new_session() -> Session:
    """
    Create a standalone Session for use outside the request/response cycle
    (e.g. inside FastAPI BackgroundTasks). Caller is responsible for closing.

    Usage:
        db = new_session()
        try:
            ...
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    """
    return SessionLocal()
