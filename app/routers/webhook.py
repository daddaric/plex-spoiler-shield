import json
import logging

from fastapi import APIRouter, Request

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
            await _handle_scrobble(payload)
        else:
            logger.debug(f"Ignoring event type: {event}")

    except Exception:
        logger.exception("Error processing Plex webhook")

    return {"status": "received"}


async def _handle_scrobble(payload: dict):
    """Handle media.scrobble — an episode was fully watched."""
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
