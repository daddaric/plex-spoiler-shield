"""Library sync and background polling service.

Reconciles watch state with Plex and obscures/restores episode metadata directly.
"""

import asyncio
import logging

import httpx

from app.config import app_config, settings
from app.services.plex_client import get_all_episodes, get_tv_library_sections
from app.services.plex_writer import (
    ObscureRequest,
    RestoreRequest,
    obscure_episode,
    restore_episode,
)
from app.services.snapshot import (
    get_obscured_for_keys,
    get_snapshot,
    mark_obscured,
    mark_restored,
    save_snapshots_batch,
)
from app.services.watch_state import bulk_update

logger = logging.getLogger("plex-spoiler-shield.sync")


async def initial_sync(client: httpx.AsyncClient) -> None:
    """Full library scan on startup — populates watch state, snapshots metadata,
    and reconciles obscured/restored state."""
    logger.info("Starting initial library sync...")
    try:
        sections = await _filtered_sections(client)
        total = 0
        obscured_count = 0
        restored_count = 0

        for section in sections:
            episodes = await get_all_episodes(client, section["key"])
            if not episodes:
                continue

            # Update watch state
            await bulk_update(episodes)

            # Snapshot all episode metadata (safe upsert)
            await save_snapshots_batch(episodes)

            total += len(episodes)

            # Reconcile: obscure unwatched, restore watched
            o, r = await _reconcile(client, episodes)
            obscured_count += o
            restored_count += r

            logger.info(
                f"  Synced section '{section['title']}': {len(episodes)} episodes, "
                f"obscured {o}, restored {r}"
            )

        logger.info(
            f"Initial sync complete — {total} episodes indexed, "
            f"{obscured_count} obscured, {restored_count} restored"
        )
    except Exception:
        logger.exception("Initial sync failed — watch state may be incomplete")


async def poll_loop(client: httpx.AsyncClient) -> None:
    """Background polling loop — reconciles watch state and metadata periodically."""
    interval = settings.poll_interval
    logger.info(f"Background poll starting (interval: {interval}s)")

    while True:
        await asyncio.sleep(interval)
        try:
            logger.debug("Running background poll...")
            sections = await _filtered_sections(client)
            total = 0
            obscured_count = 0
            restored_count = 0

            for section in sections:
                episodes = await get_all_episodes(client, section["key"])
                if not episodes:
                    continue

                await bulk_update(episodes)
                await save_snapshots_batch(episodes)
                total += len(episodes)

                o, r = await _reconcile(client, episodes)
                obscured_count += o
                restored_count += r

            logger.debug(
                f"Poll complete — reconciled {total} episodes, "
                f"obscured {obscured_count}, restored {restored_count}"
            )
        except Exception:
            logger.exception("Background poll failed — will retry next interval")


async def _reconcile(
    client: httpx.AsyncClient, episodes: list[dict]
) -> tuple[int, int]:
    """Reconcile metadata state for a list of episodes.

    Returns (obscured_count, restored_count).

    Crash safety: each episode is written to Plex then immediately marked
    in the DB, so at most one episode is inconsistent on crash.
    """
    obscured_count = 0
    restored_count = 0

    # Get current obscured state for all episode keys
    all_keys = [ep["rating_key"] for ep in episodes]
    currently_obscured = await get_obscured_for_keys(all_keys)

    for ep in episodes:
        rk = ep["rating_key"]

        if not ep["watched"] and rk not in currently_obscured:
            # Unwatched + not obscured → obscure it
            snap = await get_snapshot(rk)
            if not snap:
                continue
            req = ObscureRequest(
                section_key=ep["section_key"],
                rating_key=rk,
                episode_index=ep.get("episode_index"),
                parent_thumb=ep.get("parent_thumb"),
                grandparent_thumb=ep.get("grandparent_thumb"),
            )
            if await obscure_episode(client, req):
                await mark_obscured(rk)
                obscured_count += 1

        elif ep["watched"] and rk in currently_obscured:
            # Watched + still obscured → restore it
            snap = currently_obscured[rk]
            req = RestoreRequest(
                section_key=snap.section_key,
                rating_key=rk,
                original_title=snap.original_title,
                original_summary=snap.original_summary,
                original_tagline=snap.original_tagline,
                original_thumb=snap.original_thumb,
            )
            if await restore_episode(client, req):
                await mark_restored(rk)
                restored_count += 1

    return obscured_count, restored_count


async def _filtered_sections(client: httpx.AsyncClient) -> list[dict]:
    """Get TV sections, filtered by protected_libraries config if set."""
    sections = await get_tv_library_sections(client)
    protected = app_config.protected_libraries
    if protected:
        sections = [s for s in sections if s["title"] in protected]
        logger.debug(f"Filtered to protected libraries: {[s['title'] for s in sections]}")
    return sections
