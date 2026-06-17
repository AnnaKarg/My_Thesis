import os
from sqlalchemy import text # Χρησιμοποιείται για την εκτέλεση raw SQL εντολών
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession # Χρησιμοποιείται για τη δημιουργία async επικοινωνίας με DB
from sqlalchemy.orm import declarative_base, sessionmaker # Χρησιμοποιείται για τη δημιουργία βάσης δεδομένων

DATABASE_URL = "sqlite+aiosqlite:///./tutor_database.db" # URL για τη σύνδεση με τη βάση δεδομένων SQLite μέσω aiosqlite

# echo=True μόνο αν το DB_ECHO=true στο περιβάλλον — αποφεύγει logging SQL σε production
_db_echo = os.getenv("DB_ECHO", "false").lower() == "true"
engine = create_async_engine(DATABASE_URL, echo=_db_echo) 
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False) 

Base = declarative_base() # Βάση για τον ορισμό των μοντέλων της βάσης δεδομένων

async def init_db(): # Συνάρτηση για την αρχικοποίηση της βάσης δεδομένων
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        result = await conn.execute(text("PRAGMA table_info(users)"))
        columns = [row[1] for row in result.fetchall()]
        if "profile_checked" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN profile_checked BOOLEAN NOT NULL DEFAULT 0"))
        if "active_task_lesson_id" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN active_task_lesson_id INTEGER NOT NULL DEFAULT 0"))
        if "active_task_text" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN active_task_text TEXT NOT NULL DEFAULT ''"))
        if "active_success_criteria" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN active_success_criteria TEXT NOT NULL DEFAULT '[]'"))
        if "frequent_error_categories" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN frequent_error_categories TEXT NOT NULL DEFAULT '[]'"))
        if "avg_time_spent" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN avg_time_spent FLOAT NOT NULL DEFAULT 0.0"))
        if "solved_tasks" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN solved_tasks INTEGER NOT NULL DEFAULT 0"))
        if "understanding_level" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN understanding_level VARCHAR NOT NULL DEFAULT 'developing'"))
        if "last_assessment_decision" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN last_assessment_decision VARCHAR NOT NULL DEFAULT 'repeat'"))

        if "pending_advance" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN pending_advance BOOLEAN NOT NULL DEFAULT 0"))
        if "difficulty_probe_direction" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN difficulty_probe_direction VARCHAR NOT NULL DEFAULT ''"))
        if "avg_hints_per_task" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN avg_hints_per_task FLOAT NOT NULL DEFAULT 0.0"))

        # Index στο chat_histories.user_id για γρήγορη αναζήτηση ιστορικού ανά χρήστη
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_chat_histories_user_id ON chat_histories (user_id)"
        ))