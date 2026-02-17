import json
import logging
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Request, Response

from app.services.metadata import (
    extract_rating_keys_json,
    extract_rating_keys_xml,
    is_episode_route,
    obscure_episode_json,
    obscure_episode_xml,
)
from app.services.watch_state import is_watched_batch

logger = logging.getLogger("plex-spoiler-shield.proxy")

router = APIRouter(tags=["proxy"])


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_request(request: Request, path: str):
    """
    Catch-all reverse proxy: forwards every request to the real Plex server.
    Intercepts episode metadata responses and obscures unwatched episodes.
    """
    client = request.app.state.http_client

    # Build the upstream URL preserving query params
    url = f"/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    # Forward headers (pass through auth token, accept types, etc.)
    headers = dict(request.headers)
    for h in ("host", "transfer-encoding"):
        headers.pop(h, None)

    body = await request.body()

    upstream_resp = await client.request(
        method=request.method,
        url=url,
        headers=headers,
        content=body,
    )

    content = upstream_resp.content
    content_type = upstream_resp.headers.get("content-type", "")

    # Only intercept GET responses on routes that may contain episode metadata
    if request.method == "GET" and is_episode_route(f"/{path}"):
        content = await _maybe_obscure(content, content_type)

    # Return the (possibly modified) response to the Plex client
    response_headers = dict(upstream_resp.headers)
    for h in ("transfer-encoding", "content-encoding", "content-length"):
        response_headers.pop(h, None)

    return Response(
        content=content,
        status_code=upstream_resp.status_code,
        headers=response_headers,
    )


async def _maybe_obscure(content: bytes, content_type: str) -> bytes:
    """Detect response format, check watch state, and obscure if needed."""
    try:
        if "xml" in content_type or content.lstrip()[:5] in (b"<?xml", b"<Medi"):
            return await _obscure_xml(content)
        elif "json" in content_type:
            return await _obscure_json(content)
    except Exception:
        logger.exception("Error during metadata interception — passing through unmodified")

    return content


async def _obscure_xml(content: bytes) -> bytes:
    root = ET.fromstring(content)
    rating_keys = extract_rating_keys_xml(root)
    if not rating_keys:
        return content

    watched_keys = await is_watched_batch(rating_keys)
    if obscure_episode_xml(root, watched_keys):
        return ET.tostring(root, encoding="unicode").encode("utf-8")

    return content


async def _obscure_json(content: bytes) -> bytes:
    data = json.loads(content)
    rating_keys = extract_rating_keys_json(data)
    if not rating_keys:
        return content

    watched_keys = await is_watched_batch(rating_keys)
    if obscure_episode_json(data, watched_keys):
        return json.dumps(data).encode("utf-8")

    return content
