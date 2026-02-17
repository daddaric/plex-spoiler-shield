"""Metadata interceptor for Plex API responses.

Detects episode metadata in Plex responses (XML and JSON) and obscures
unwatched episodes — replacing titles, summaries, thumbnails, and guest stars
based on the obfuscation config.
"""

import logging
import re
from xml.etree import ElementTree as ET

from app.config import app_config

logger = logging.getLogger("plex-spoiler-shield.metadata")

obf = app_config.obfuscation
title_template = app_config.title_template

# Plex API routes that return episode metadata
EPISODE_ROUTE_PATTERNS = [
    re.compile(r"^/library/metadata/\d+$"),
    re.compile(r"^/library/metadata/\d+/children$"),
    re.compile(r"^/library/sections/\d+/all"),
    re.compile(r"^/library/sections/\d+/recentlyAdded"),
    re.compile(r"^/library/sections/\d+/onDeck"),
    re.compile(r"^/hubs"),
]


def is_episode_route(path: str) -> bool:
    return any(p.match(path) for p in EPISODE_ROUTE_PATTERNS)


def obscure_episode_xml(root: ET.Element, watched_keys: dict[str, bool]) -> bool:
    modified = False
    for video in root.iter("Video"):
        if video.get("type") != "episode":
            continue
        rating_key = video.get("ratingKey")
        if not rating_key or watched_keys.get(rating_key, False):
            continue
        _obscure_xml_episode(video)
        modified = True
    return modified


def _obscure_xml_episode(video: ET.Element) -> None:
    episode_index = video.get("index", "?")

    if obf.title:
        video.set("title", title_template.replace("{n}", str(episode_index)))

    if obf.summary:
        if "summary" in video.attrib:
            video.set("summary", "")
        if "tagline" in video.attrib:
            video.set("tagline", "")

    if obf.thumbnail:
        parent_thumb = video.get("parentThumb") or video.get("grandparentThumb")
        if parent_thumb:
            video.set("thumb", parent_thumb)
            if "art" in video.attrib:
                grandparent_art = video.get("grandparentArt")
                if grandparent_art:
                    video.set("art", grandparent_art)

    if obf.roles:
        for role in video.findall("Role"):
            video.remove(role)

    logger.debug(f"Obscured episode ratingKey={video.get('ratingKey')} index={episode_index}")


def obscure_episode_json(data: dict, watched_keys: dict[str, bool]) -> bool:
    modified = False
    metadata_list = data.get("MediaContainer", {}).get("Metadata", [])
    for item in metadata_list:
        if item.get("type") != "episode":
            continue
        rating_key = str(item.get("ratingKey", ""))
        if not rating_key or watched_keys.get(rating_key, False):
            continue
        _obscure_json_episode(item)
        modified = True
    return modified


def _obscure_json_episode(item: dict) -> None:
    episode_index = item.get("index", "?")

    if obf.title:
        item["title"] = title_template.replace("{n}", str(episode_index))

    if obf.summary:
        item["summary"] = ""
        if "tagline" in item:
            item["tagline"] = ""

    if obf.thumbnail:
        parent_thumb = item.get("parentThumb") or item.get("grandparentThumb")
        if parent_thumb:
            item["thumb"] = parent_thumb
        grandparent_art = item.get("grandparentArt")
        if grandparent_art:
            item["art"] = grandparent_art

    if obf.roles:
        item.pop("Role", None)

    logger.debug(f"Obscured episode ratingKey={item.get('ratingKey')} index={episode_index}")


def extract_rating_keys_xml(root: ET.Element) -> list[str]:
    keys = []
    for video in root.iter("Video"):
        if video.get("type") == "episode":
            rk = video.get("ratingKey")
            if rk:
                keys.append(rk)
    return keys


def extract_rating_keys_json(data: dict) -> list[str]:
    keys = []
    for item in data.get("MediaContainer", {}).get("Metadata", []):
        if item.get("type") == "episode":
            rk = str(item.get("ratingKey", ""))
            if rk:
                keys.append(rk)
    return keys
