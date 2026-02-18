"""CRUD operations for the metadata_snapshot table.

Stores original episode metadata before obscuring, enabling safe restore.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.config import settings

logger = logging.getLogger("plex-spoiler-shield.snapshot")

DB_PATH = settings.db_path


def _connect() -> aiosqlite.Connection:
    return aiosqlite.connect(DB_PATH)


@dataclass
class EpisodeSnapshot:
    rating_key: str
    section_key: str
    original_title: Optional[str]
    original_summary: Optional[str]
    original_tagline: Optional[str]
    original_thumb: Optional[str]
    episode_index: Optional[int]
    parent_thumb: Optional[str]
    grandparent_thumb: Optional[str]
    obscured: bool


async def get_snapshot(rating_key: str) -> Optional[EpisodeSnapshot]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM metadata_snapshot WHERE rating_key = ?",
            (rating_key,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_snapshot(row)


async def save_snapshots_batch(snapshots: list[dict]) -> None:
    """Upsert episode snapshots. Safety: does NOT overwrite original_* fields
    if the row is currently marked as obscured (prevents saving obscured values
    as originals).
    """
    if not snapshots:
        return
    now = datetime.now(timezone.utc).isoformat()
    async with _connect() as db:
        await db.executemany(
            """INSERT INTO metadata_snapshot
               (rating_key, section_key, original_title, original_summary,
                original_tagline, original_thumb, episode_index,
                parent_thumb, grandparent_thumb, obscured, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
               ON CONFLICT(rating_key) DO UPDATE SET
                 section_key = excluded.section_key,
                 original_title = CASE WHEN metadata_snapshot.obscured = 0
                   THEN excluded.original_title ELSE metadata_snapshot.original_title END,
                 original_summary = CASE WHEN metadata_snapshot.obscured = 0
                   THEN excluded.original_summary ELSE metadata_snapshot.original_summary END,
                 original_tagline = CASE WHEN metadata_snapshot.obscured = 0
                   THEN excluded.original_tagline ELSE metadata_snapshot.original_tagline END,
                 original_thumb = CASE WHEN metadata_snapshot.obscured = 0
                   THEN excluded.original_thumb ELSE metadata_snapshot.original_thumb END,
                 episode_index = excluded.episode_index,
                 parent_thumb = excluded.parent_thumb,
                 grandparent_thumb = excluded.grandparent_thumb,
                 updated_at = excluded.updated_at
            """,
            [
                (
                    s["rating_key"],
                    s["section_key"],
                    s.get("title"),
                    s.get("summary"),
                    s.get("tagline"),
                    s.get("thumb"),
                    s.get("episode_index"),
                    s.get("parent_thumb"),
                    s.get("grandparent_thumb"),
                    now,
                    now,
                )
                for s in snapshots
            ],
        )
        await db.commit()
    logger.debug(f"Saved {len(snapshots)} metadata snapshots")


async def mark_obscured(rating_key: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with _connect() as db:
        await db.execute(
            "UPDATE metadata_snapshot SET obscured = 1, updated_at = ? WHERE rating_key = ?",
            (now, rating_key),
        )
        await db.commit()


async def mark_restored(rating_key: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with _connect() as db:
        await db.execute(
            "UPDATE metadata_snapshot SET obscured = 0, updated_at = ? WHERE rating_key = ?",
            (now, rating_key),
        )
        await db.commit()


async def get_all_obscured() -> list[EpisodeSnapshot]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM metadata_snapshot WHERE obscured = 1"
        )
        rows = await cursor.fetchall()
        return [_row_to_snapshot(row) for row in rows]


async def get_obscured_for_keys(rating_keys: list[str]) -> dict[str, EpisodeSnapshot]:
    if not rating_keys:
        return {}
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        placeholders = ",".join("?" for _ in rating_keys)
        cursor = await db.execute(
            f"SELECT * FROM metadata_snapshot WHERE rating_key IN ({placeholders}) AND obscured = 1",
            rating_keys,
        )
        rows = await cursor.fetchall()
        return {row["rating_key"]: _row_to_snapshot(row) for row in rows}


def _row_to_snapshot(row) -> EpisodeSnapshot:
    return EpisodeSnapshot(
        rating_key=row["rating_key"],
        section_key=row["section_key"],
        original_title=row["original_title"],
        original_summary=row["original_summary"],
        original_tagline=row["original_tagline"],
        original_thumb=row["original_thumb"],
        episode_index=row["episode_index"],
        parent_thumb=row["parent_thumb"],
        grandparent_thumb=row["grandparent_thumb"],
        obscured=bool(row["obscured"]),
    )
