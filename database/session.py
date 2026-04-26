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