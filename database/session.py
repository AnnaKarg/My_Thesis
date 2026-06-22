import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

# Υποστηρίζει SQLite (local dev) και PostgreSQL (production via Render/Neon)
_raw_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./tutor_database.db")

# Render/Neon δίνουν "postgres://" — SQLAlchemy θέλει "postgresql+asyncpg://"
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _raw_url.startswith("postgresql://") and "+asyncpg" not in _raw_url:
    _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)

DATABASE_URL = _raw_url
_is_sqlite = DATABASE_URL.startswith("sqlite")

_db_echo = os.getenv("DB_ECHO", "false").lower() == "true"
engine = create_async_engine(DATABASE_URL, echo=_db_echo)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        if _is_sqlite:
            # SQLite: ελέγχουμε/προσθέτουμε columns που προστέθηκαν incrementally
            result = await conn.execute(text("PRAGMA table_info(users)"))
            columns = [row[1] for row in result.fetchall()]
            extra_columns = [
                ("profile_checked",          "BOOLEAN NOT NULL DEFAULT 0"),
                ("active_task_lesson_id",     "INTEGER NOT NULL DEFAULT 0"),
                ("active_task_text",          "TEXT NOT NULL DEFAULT ''"),
                ("active_success_criteria",   "TEXT NOT NULL DEFAULT '[]'"),
                ("frequent_error_categories", "TEXT NOT NULL DEFAULT '[]'"),
                ("avg_time_spent",            "FLOAT NOT NULL DEFAULT 0.0"),
                ("solved_tasks",              "INTEGER NOT NULL DEFAULT 0"),
                ("understanding_level",       "VARCHAR NOT NULL DEFAULT 'developing'"),
                ("last_assessment_decision",  "VARCHAR NOT NULL DEFAULT 'repeat'"),
                ("pending_advance",           "BOOLEAN NOT NULL DEFAULT 0"),
                ("difficulty_probe_direction","VARCHAR NOT NULL DEFAULT ''"),
                ("avg_hints_per_task",        "FLOAT NOT NULL DEFAULT 0.0"),
            ]
            for col_name, col_def in extra_columns:
                if col_name not in columns:
                    await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))

            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_chat_histories_user_id ON chat_histories (user_id)"
            ))
        # PostgreSQL: create_all δημιουργεί τα πάντα από το model — δεν χρειάζεται ALTER TABLE
