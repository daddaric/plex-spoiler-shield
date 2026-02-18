"""Plex API write operations for modifying episode metadata."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import app_config, settings

logger = logging.getLogger("plex-spoiler-shield.plex_writer")

# Limit concurrent Plex API writes
_semaphore = asyncio.Semaphore(5)

obf = app_config.obfuscation
title_template = app_config.title_template


def _headers() -> dict:
    return {"X-Plex-Token": settings.plex_token}


@dataclass
class ObscureRequest:
    section_key: str
    rating_key: str
    episode_index: Optional[int]
    parent_thumb: Optional[str]
    grandparent_thumb: Optional[str]


@dataclass
class RestoreRequest:
    section_key: str
    rating_key: str
    original_title: Optional[str]
    original_summary: Optional[str]
    original_tagline: Optional[str]
    original_thumb: Optional[str]


async def obscure_episode(client: httpx.AsyncClient, req: ObscureRequest) -> bool:
    """PUT obscured metadata to Plex for a single episode. Returns True on success."""
    params = {"type": "4", "id": req.rating_key}

    if obf.title:
        index_str = str(req.episode_index) if req.episode_index is not None else "?"
        params["title.value"] = title_template.replace("{n}", index_str)
        params["title.locked"] = "1"

    if obf.summary:
        params["summary.value"] = ""
        params["summary.locked"] = "1"
        params["tagline.value"] = ""
        params["tagline.locked"] = "1"

    if obf.thumbnail:
        # Use parent (season) thumb, fall back to grandparent (show) thumb
        replacement_thumb = req.parent_thumb or req.grandparent_thumb
        if replacement_thumb:
            params["thumb.value"] = replacement_thumb
            params["thumb.locked"] = "1"

    async with _semaphore:
        try:
            resp = await client.put(
                f"/library/sections/{req.section_key}/all",
                params=params,
                headers=_headers(),
            )
            resp.raise_for_status()
            logger.debug(f"Obscured episode {req.rating_key}")
            return True
        except Exception:
            logger.exception(f"Failed to obscure episode {req.rating_key}")
            return False


async def restore_episode(client: httpx.AsyncClient, req: RestoreRequest) -> bool:
    """PUT original metadata back to Plex and unlock fields. Returns True on success."""
    params = {"type": "4", "id": req.rating_key}

    if obf.title and req.original_title is not None:
        params["title.value"] = req.original_title
        params["title.locked"] = "0"

    if obf.summary:
        if req.original_summary is not None:
            params["summary.value"] = req.original_summary
            params["summary.locked"] = "0"
        if req.original_tagline is not None:
            params["tagline.value"] = req.original_tagline
            params["tagline.locked"] = "0"

    if obf.thumbnail and req.original_thumb is not None:
        params["thumb.value"] = req.original_thumb
        params["thumb.locked"] = "0"

    async with _semaphore:
        try:
            resp = await client.put(
                f"/library/sections/{req.section_key}/all",
                params=params,
                headers=_headers(),
            )
            resp.raise_for_status()

            # Trigger a metadata refresh to re-fetch from agents
            await client.put(
                f"/library/metadata/{req.rating_key}/refresh",
                headers=_headers(),
            )

            logger.debug(f"Restored episode {req.rating_key}")
            return True
        except Exception:
            logger.exception(f"Failed to restore episode {req.rating_key}")
            return False


async def obscure_episodes_batch(
    client: httpx.AsyncClient, episodes: list[ObscureRequest]
) -> list[str]:
    """Obscure multiple episodes. Returns list of succeeded rating_keys."""
    tasks = [obscure_episode(client, ep) for ep in episodes]
    results = await asyncio.gather(*tasks)
    return [ep.rating_key for ep, ok in zip(episodes, results) if ok]


async def restore_episodes_batch(
    client: httpx.AsyncClient, episodes: list[RestoreRequest]
) -> list[str]:
    """Restore multiple episodes. Returns list of succeeded rating_keys."""
    tasks = [restore_episode(client, ep) for ep in episodes]
    results = await asyncio.gather(*tasks)
    return [ep.rating_key for ep, ok in zip(episodes, results) if ok]
