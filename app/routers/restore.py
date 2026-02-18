"""Restore and status endpoints for managing obscured episode metadata."""

import logging

from fastapi import APIRouter, Request

from app.services.plex_writer import RestoreRequest, restore_episode
from app.services.snapshot import get_all_obscured, mark_restored

logger = logging.getLogger("plex-spoiler-shield.restore")

router = APIRouter(tags=["restore"])


@router.post("/restore/all")
async def restore_all(request: Request):
    """Restore ALL obscured episodes to their original metadata. Safety valve."""
    client = request.app.state.http_client
    obscured = await get_all_obscured()

    if not obscured:
        return {"status": "ok", "restored": 0, "message": "No episodes currently obscured"}

    restored_count = 0
    failed_count = 0

    for snap in obscured:
        req = RestoreRequest(
            section_key=snap.section_key,
            rating_key=snap.rating_key,
            original_title=snap.original_title,
            original_summary=snap.original_summary,
            original_tagline=snap.original_tagline,
            original_thumb=snap.original_thumb,
        )
        if await restore_episode(client, req):
            await mark_restored(snap.rating_key)
            restored_count += 1
        else:
            failed_count += 1

    logger.info(f"Restore all: restored {restored_count}, failed {failed_count}")
    return {
        "status": "ok",
        "restored": restored_count,
        "failed": failed_count,
    }


@router.get("/status")
async def status():
    """Return count and list of currently obscured episodes."""
    obscured = await get_all_obscured()
    return {
        "obscured_count": len(obscured),
        "episodes": [
            {
                "rating_key": s.rating_key,
                "section_key": s.section_key,
                "original_title": s.original_title,
                "episode_index": s.episode_index,
            }
            for s in obscured
        ],
    }
