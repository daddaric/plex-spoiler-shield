"""Library sync and background polling service."""

import asyncio
import logging

import httpx

from app.config import app_config, settings
from app.services.plex_client import get_all_episodes, get_tv_library_sections
from app.services.watch_state import bulk_update

logger = logging.getLogger("plex-spoiler-shield.sync")


async def initial_sync(client: httpx.AsyncClient) -> None:
    """Full library scan on startup — populates watch state for all episodes."""
    logger.info("Starting initial library sync...")
    try:
        sections = await _filtered_sections(client)
        total = 0
        for section in sections:
            episodes = await get_all_episodes(client, section["key"])
            if episodes:
                await bulk_update(episodes)
                total += len(episodes)
            logger.info(f"  Synced section '{section['title']}': {len(episodes)} episodes")

        logger.info(f"Initial sync complete — {total} episodes indexed")
    except Exception:
        logger.exception("Initial sync failed — proxy will still work but watch state may be incomplete")


async def poll_loop(client: httpx.AsyncClient) -> None:
    """Background polling loop — reconciles watch state periodically.

    Catches any scrobble events missed due to webhook failures or restarts.
    """
    interval = settings.poll_interval
    logger.info(f"Background poll starting (interval: {interval}s)")

    while True:
        await asyncio.sleep(interval)
        try:
            logger.debug("Running background poll...")
            sections = await _filtered_sections(client)
            total = 0
            for section in sections:
                episodes = await get_all_episodes(client, section["key"])
                if episodes:
                    await bulk_update(episodes)
                    total += len(episodes)

            logger.debug(f"Poll complete — reconciled {total} episodes")
        except Exception:
            logger.exception("Background poll failed — will retry next interval")


async def _filtered_sections(client: httpx.AsyncClient) -> list[dict]:
    """Get TV sections, filtered by protected_libraries config if set."""
    sections = await get_tv_library_sections(client)
    protected = app_config.protected_libraries
    if protected:
        sections = [s for s in sections if s["title"] in protected]
        logger.debug(f"Filtered to protected libraries: {[s['title'] for s in sections]}")
    return sections
