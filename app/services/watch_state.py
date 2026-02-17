import logging
from datetime import datetime, timezone

import aiosqlite

from app.config import settings

logger = logging.getLogger("plex-spoiler-shield.watch_state")

DB_PATH = settings.db_path


def _connect() -> aiosqlite.Connection:
    conn = aiosqlite.connect(DB_PATH)
    return conn


async def is_watched(rating_key: str) -> bool:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT watched FROM watch_state WHERE rating_key = ?",
            (rating_key,),
        )
        row = await cursor.fetchone()
        return bool(row and row["watched"])


async def is_watched_batch(rating_keys: list[str]) -> dict[str, bool]:
    if not rating_keys:
        return {}
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        placeholders = ",".join("?" for _ in rating_keys)
        cursor = await db.execute(
            f"SELECT rating_key, watched FROM watch_state WHERE rating_key IN ({placeholders})",
            rating_keys,
        )
        rows = await cursor.fetchall()
        result = {rk: False for rk in rating_keys}
        for row in rows:
            result[row["rating_key"]] = bool(row["watched"])
        return result


async def mark_watched(rating_key: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with _connect() as db:
        await db.execute(
            """INSERT INTO watch_state (rating_key, watched, watched_at)
               VALUES (?, 1, ?)
               ON CONFLICT(rating_key) DO UPDATE SET watched = 1, watched_at = ?""",
            (rating_key, now, now),
        )
        await db.commit()
    logger.info(f"Marked {rating_key} as watched")


async def mark_unwatched(rating_key: str) -> None:
    async with _connect() as db:
        await db.execute(
            """INSERT INTO watch_state (rating_key, watched, watched_at)
               VALUES (?, 0, NULL)
               ON CONFLICT(rating_key) DO UPDATE SET watched = 0, watched_at = NULL""",
            (rating_key,),
        )
        await db.commit()
    logger.debug(f"Marked {rating_key} as unwatched")


async def bulk_update(items: list[dict]) -> None:
    """Update watch state for many episodes at once.

    Each item: {"rating_key": str, "watched": bool}
    """
    if not items:
        return
    now = datetime.now(timezone.utc).isoformat()
    async with _connect() as db:
        await db.executemany(
            """INSERT INTO watch_state (rating_key, watched, watched_at)
               VALUES (?, ?, ?)
               ON CONFLICT(rating_key) DO UPDATE SET watched = ?, watched_at = ?""",
            [
                (
                    item["rating_key"],
                    int(item["watched"]),
                    now if item["watched"] else None,
                    int(item["watched"]),
                    now if item["watched"] else None,
                )
                for item in items
            ],
        )
        await db.commit()
    logger.info(f"Bulk updated {len(items)} watch states")
