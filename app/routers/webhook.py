import json
import logging

from fastapi import APIRouter, Request

from app.services.plex_writer import RestoreRequest, restore_episode
from app.services.snapshot import get_snapshot, mark_restored
from app.services.watch_state import mark_watched

logger = logging.getLogger("plex-spoiler-shield.webhook")

router = APIRouter(tags=["webhook"])


@router.post("/webhook/plex")
async def plex_webhook(request: Request):
    """Receive Plex webhook events.

    Plex sends webhooks as multipart/form-data with a 'payload' field
    containing a JSON string describing the event.
    """
    try:
        form = await request.form()
        payload_raw = form.get("payload")
        if not payload_raw:
            logger.warning("Webhook received with no payload field")
            return {"status": "ignored", "reason": "no payload"}

        payload = json.loads(payload_raw)
        event = payload.get("event", "")
        logger.info(f"Webhook event: {event}")

        if event == "media.scrobble":
            await _handle_scrobble(payload, request.app.state.http_client)
        else:
            logger.debug(f"Ignoring event type: {event}")

    except Exception:
        logger.exception("Error processing Plex webhook")

    return {"status": "received"}


async def _handle_scrobble(payload: dict, http_client):
    """Handle media.scrobble — an episode was fully watched.

    Marks the episode as watched and restores original metadata if it was obscured.
    """
    metadata = payload.get("Metadata", {})
    media_type = metadata.get("type", "")
    rating_key = str(metadata.get("ratingKey", ""))

    if media_type != "episode":
        logger.debug(f"Scrobble for non-episode type: {media_type}")
        return

    if not rating_key:
        logger.warning("Scrobble event missing ratingKey")
        return

    title = metadata.get("grandparentTitle", "?")
    season = metadata.get("parentIndex", "?")
    episode = metadata.get("index", "?")

    await mark_watched(rating_key)
    logger.info(f"Scrobble: {title} S{season}E{episode} (ratingKey={rating_key}) marked watched")

    # Restore original metadata if this episode was obscured
    snap = await get_snapshot(rating_key)
    if snap and snap.obscured:
        req = RestoreRequest(
            section_key=snap.section_key,
            rating_key=rating_key,
            original_title=snap.original_title,
            original_summary=snap.original_summary,
            original_tagline=snap.original_tagline,
            original_thumb=snap.original_thumb,
        )
        if await restore_episode(http_client, req):
            await mark_restored(rating_key)
            logger.info(f"Restored metadata for episode {rating_key}")
        else:
            logger.error(f"Failed to restore metadata for episode {rating_key}")
