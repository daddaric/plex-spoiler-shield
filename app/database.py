import aiosqlite
import os
from app.config import settings

DB_PATH = settings.db_path


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS watch_state (
                rating_key TEXT PRIMARY KEY,
                watched INTEGER NOT NULL DEFAULT 0,
                watched_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS metadata_snapshot (
                rating_key TEXT PRIMARY KEY,
                section_key TEXT NOT NULL,
                original_title TEXT,
                original_summary TEXT,
                original_tagline TEXT,
                original_thumb TEXT,
                episode_index INTEGER,
                parent_thumb TEXT,
                grandparent_thumb TEXT,
                obscured INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.commit()


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
