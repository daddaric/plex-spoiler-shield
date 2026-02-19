"""Plex API write operations for modifying episode metadata."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote
from xml.etree import ElementTree as ET

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
    """Obscure metadata for a single episode. Returns True on success."""
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
        # Lock the thumb field to prevent library scans from overwriting
        params["thumb.locked"] = "1"

    async with _semaphore:
        try:
            resp = await client.put(
                f"/library/sections/{req.section_key}/all",
                params=params,
                headers=_headers(),
            )
            resp.raise_for_status()

            # Replace episode thumbnail by uploading the season/show poster as a
            # custom poster. thumb.value via sections/all is silently ignored by Plex
            # for episodes; the correct approach is a binary POST to /posters.
            if obf.thumbnail:
                source_thumb = req.parent_thumb or req.grandparent_thumb
                if source_thumb:
                    await _upload_poster(client, req.rating_key, source_thumb)

            logger.debug(f"Obscured episode {req.rating_key}")
            return True
        except Exception:
            logger.exception(f"Failed to obscure episode {req.rating_key}")
            return False


async def restore_episode(client: httpx.AsyncClient, req: RestoreRequest) -> bool:
    """Restore original metadata for a single episode. Returns True on success."""
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

    if obf.thumbnail:
        # Unlock so the poster reselection below and refresh can overwrite it
        params["thumb.locked"] = "0"

    async with _semaphore:
        try:
            resp = await client.put(
                f"/library/sections/{req.section_key}/all",
                params=params,
                headers=_headers(),
            )
            resp.raise_for_status()

            if obf.thumbnail:
                await _restore_original_poster(client, req.rating_key)

            # Trigger metadata refresh to re-fetch from agents
            await client.put(
                f"/library/metadata/{req.rating_key}/refresh",
                headers=_headers(),
            )

            logger.debug(f"Restored episode {req.rating_key}")
            return True
        except Exception:
            logger.exception(f"Failed to restore episode {req.rating_key}")
            return False


async def _upload_poster(
    client: httpx.AsyncClient, rating_key: str, source_thumb: str
) -> None:
    """Upload an image from source_thumb as a custom poster for the episode.

    Fetches the image bytes from source_thumb then POSTs them to the episode's
    /posters endpoint. Plex auto-selects the uploaded poster, and the episode's
    thumb attribute updates to the new custom image.
    """
    source_resp = await client.get(source_thumb, headers=_headers())
    if not source_resp.is_success:
        logger.warning(f"Failed to fetch source poster from {source_thumb}: {source_resp.status_code}")
        return

    upload_resp = await client.post(
        f"/library/metadata/{rating_key}/posters",
        content=source_resp.content,
        headers={**_headers(), "Content-Type": "image/jpeg"},
    )
    if not upload_resp.is_success:
        logger.warning(f"Failed to upload poster for episode {rating_key}: {upload_resp.status_code}")


async def _restore_original_poster(
    client: httpx.AsyncClient, rating_key: str
) -> None:
    """Reselect the original metadata agent poster, replacing our custom upload.

    Fetches the posters list, finds the first non-upload poster (from the metadata
    agent), and selects it via PUT /poster?url={key}.
    """
    posters_resp = await client.get(
        f"/library/metadata/{rating_key}/posters",
        headers={**_headers(), "Accept": "application/xml"},
    )
    if not posters_resp.is_success:
        logger.warning(f"Failed to get posters list for episode {rating_key}")
        return

    root = ET.fromstring(posters_resp.content)
    for photo in root.iter("Photo"):
        rk = photo.get("ratingKey", "")
        # Skip our uploaded poster — select the first agent-provided poster
        if not rk.startswith("upload://"):
            await client.put(
                f"/library/metadata/{rating_key}/poster",
                params={"url": rk},
                headers=_headers(),
            )
            return

    logger.warning(f"No agent poster found for episode {rating_key} — refresh will handle it")


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
