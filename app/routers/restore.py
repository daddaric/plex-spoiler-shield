"""Restore and status endpoints for managing obscured episode metadata."""

import logging

from fastapi import APIRouter, Request

from app.services.plex_writer import RestoreRequest, reapply_episode_thumbnail, restore_episode
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


@router.post("/reindex/thumbnails")
async def reindex_thumbnails(request: Request):
    """Re-upload letterboxed thumbnails for all currently obscured episodes.

    Use after updating thumbnail processing logic to reprocess existing obscured content
    with the correct aspect ratio.
    """
    client = request.app.state.http_client
    obscured = await get_all_obscured()

    if not obscured:
        return {"status": "ok", "updated": 0, "skipped": 0, "failed": 0, "message": "No episodes currently obscured"}

    updated = 0
    skipped = 0
    failed = 0

    for snap in obscured:
        if not (snap.parent_thumb or snap.grandparent_thumb):
            skipped += 1
            continue
        if await reapply_episode_thumbnail(client, snap.rating_key, snap.parent_thumb, snap.grandparent_thumb):
            updated += 1
        else:
            failed += 1

    logger.info(f"Reindex thumbnails: updated {updated}, skipped {skipped}, failed {failed}")
    return {"status": "ok", "updated": updated, "skipped": skipped, "failed": failed}


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
