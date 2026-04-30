from sqlalchemy import text # Χρησιμοποιείται για την εκτέλεση raw SQL εντολών
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession # Χρησιμοποιείται για τη δημιουργία async επικοινωνίας με DB
from sqlalchemy.orm import declarative_base, sessionmaker # Χρησιμοποιείται για τη δημιουργία βάσης δεδομένων

DATABASE_URL = "sqlite+aiosqlite:///./tutor_database.db" # URL για τη σύνδεση με τη βάση δεδομένων SQLite μέσω aiosqlite

engine = create_async_engine(DATABASE_URL, echo=True) 
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