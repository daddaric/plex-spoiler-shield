"""Plex API client for querying library sections and watch state."""

import logging
from xml.etree import ElementTree as ET

import httpx

from app.config import settings

logger = logging.getLogger("plex-spoiler-shield.plex_client")


def _headers() -> dict:
    return {
        "X-Plex-Token": settings.plex_token,
        "Accept": "application/xml",
    }


async def get_tv_library_sections(client: httpx.AsyncClient) -> list[dict]:
    """Get all TV show library sections from Plex."""
    resp = await client.get("/library/sections", headers=_headers())
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    sections = []
    for directory in root.iter("Directory"):
        if directory.get("type") == "show":
            sections.append({
                "key": directory.get("key"),
                "title": directory.get("title"),
            })
    logger.info(f"Found {len(sections)} TV library section(s): {[s['title'] for s in sections]}")
    return sections


async def get_all_episodes(client: httpx.AsyncClient, section_key: str) -> list[dict]:
    """Get all episodes in a library section with their watch state.

    type=4 filters to episodes only.
    """
    episodes = []
    resp = await client.get(
        f"/library/sections/{section_key}/all",
        params={"type": "4"},
        headers=_headers(),
    )
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    for video in root.iter("Video"):
        rating_key = video.get("ratingKey")
        if not rating_key:
            continue

        view_count = int(video.get("viewCount", "0"))
        index_str = video.get("index")
        episodes.append({
            "rating_key": rating_key,
            "section_key": section_key,
            "watched": view_count > 0,
            "title": video.get("title"),
            "summary": video.get("summary"),
            "tagline": video.get("tagline"),
            "thumb": video.get("thumb"),
            "episode_index": int(index_str) if index_str else None,
            "parent_thumb": video.get("parentThumb"),
            "grandparent_thumb": video.get("grandparentThumb"),
        })

    return episodes


async def get_recently_watched_episodes(client: httpx.AsyncClient, section_key: str) -> list[dict]:
    """Get watched episodes in a section — used for incremental polling.

    Queries episodes filtered to watched only (unwatched=0 is not a real param,
    so we fetch all and filter by viewCount > 0).
    """
    all_eps = await get_all_episodes(client, section_key)
    return [ep for ep in all_eps if ep["watched"]]
