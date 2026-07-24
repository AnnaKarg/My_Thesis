import os
import re
import ssl as _ssl_module
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

_raw_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./tutor_database.db")

# Render/Neon δίνουν "postgres://" — SQLAlchemy θέλει "postgresql+asyncpg://"
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _raw_url.startswith("postgresql://") and "+asyncpg" not in _raw_url:
    _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# asyncpg δεν δέχεται sslmode= στο URL — το αφαιρούμε και το περνάμε ως connect_arg
if "sslmode" in _raw_url:
    _raw_url = re.sub(r'[?&]sslmode=\w+', '', _raw_url).rstrip('?&')

DATABASE_URL = _raw_url
_is_sqlite = DATABASE_URL.startswith("sqlite")

# SSL context για PostgreSQL (Neon απαιτεί SSL)
_connect_args = {}
if not _is_sqlite:
    _ssl_ctx = _ssl_module.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl_module.CERT_NONE
    _connect_args = {"ssl": _ssl_ctx}

_db_echo = os.getenv("DB_ECHO", "false").lower() == "true"
engine = create_async_engine(DATABASE_URL, echo=_db_echo, connect_args=_connect_args)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        if _is_sqlite:
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
                ("practice_streak_current",       "INTEGER NOT NULL DEFAULT 0"),
                ("practice_streak_goal",          "INTEGER NOT NULL DEFAULT 0"),
                ("practice_lesson_correct_streak", "TEXT NOT NULL DEFAULT '{}'"),
            ]
            for col_name, col_def in extra_columns:
                if col_name not in columns:
                    await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))

            # Migration: new columns on chat_histories
            result_ch = await conn.execute(text("PRAGMA table_info(chat_histories)"))
            ch_columns = [row[1] for row in result_ch.fetchall()]
            for col_name, col_def in [
                ("session_id", "INTEGER NOT NULL DEFAULT 0"),
                ("created_at", "TEXT NOT NULL DEFAULT ''"),
            ]:
                if col_name not in ch_columns:
                    await conn.execute(text(f"ALTER TABLE chat_histories ADD COLUMN {col_name} {col_def}"))

            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_chat_histories_user_id ON chat_histories (user_id)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_chat_histories_session_id ON chat_histories (session_id)"
            ))
        else:
            # PostgreSQL: ADD COLUMN IF NOT EXISTS (idempotent)
            for stmt in [
                "ALTER TABLE chat_histories ADD COLUMN IF NOT EXISTS session_id INTEGER DEFAULT 0",
                "ALTER TABLE chat_histories ADD COLUMN IF NOT EXISTS created_at TEXT DEFAULT ''",
                "CREATE INDEX IF NOT EXISTS ix_chat_histories_session_id ON chat_histories (session_id)",
                # users: ίδιες στήλες με το SQLite migration list παραπάνω — έλειπαν εντελώς εδώ,
                # προκαλώντας 500 σε ΚΑΘΕ query πάνω στο User (login/register/chat) στο production.
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_checked BOOLEAN DEFAULT FALSE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS active_task_lesson_id INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS active_task_text TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS active_success_criteria TEXT DEFAULT '[]'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS frequent_error_categories TEXT DEFAULT '[]'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_time_spent FLOAT DEFAULT 0.0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS solved_tasks INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS understanding_level VARCHAR DEFAULT 'developing'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_assessment_decision VARCHAR DEFAULT 'repeat'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_advance BOOLEAN DEFAULT FALSE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS difficulty_probe_direction VARCHAR DEFAULT ''",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_hints_per_task FLOAT DEFAULT 0.0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS practice_streak_current INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS practice_streak_goal INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS practice_lesson_correct_streak TEXT DEFAULT '{}'",
            ]:
                try:
                    await conn.execute(text(stmt))
                except Exception:
                    pass
