"""End-to-end tests: full proxy flow with a mocked Plex upstream."""

import json
from xml.etree import ElementTree as ET

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response as HttpxResponse
from fastapi import FastAPI

from app.database import init_db
from app.routers import proxy, webhook
from app.services.watch_state import mark_watched


PLEX_XML_EPISODES = """<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer size="2">
  <Video ratingKey="301" type="episode" index="1"
         title="Winter Is Coming"
         summary="Ned Stark is asked to serve as Hand of the King."
         thumb="/library/metadata/301/thumb"
         art="/library/metadata/301/art"
         parentThumb="/library/metadata/50/thumb"
         grandparentThumb="/library/metadata/10/thumb"
         grandparentArt="/library/metadata/10/art">
    <Role tag="Sean Bean"/>
  </Video>
  <Video ratingKey="302" type="episode" index="2"
         title="The Kingsroad"
         summary="The royal party heads north."
         thumb="/library/metadata/302/thumb"
         parentThumb="/library/metadata/50/thumb"
         grandparentThumb="/library/metadata/10/thumb"
         grandparentArt="/library/metadata/10/art">
  </Video>
</MediaContainer>"""

PLEX_JSON_EPISODES = {
    "MediaContainer": {
        "Metadata": [
            {
                "ratingKey": "301",
                "type": "episode",
                "index": 1,
                "title": "Winter Is Coming",
                "summary": "Ned Stark is asked to serve as Hand of the King.",
                "thumb": "/library/metadata/301/thumb",
                "art": "/library/metadata/301/art",
                "parentThumb": "/library/metadata/50/thumb",
                "grandparentThumb": "/library/metadata/10/thumb",
                "grandparentArt": "/library/metadata/10/art",
                "Role": [{"tag": "Sean Bean"}],
            },
            {
                "ratingKey": "302",
                "type": "episode",
                "index": 2,
                "title": "The Kingsroad",
                "summary": "The royal party heads north.",
                "thumb": "/library/metadata/302/thumb",
                "parentThumb": "/library/metadata/50/thumb",
                "grandparentThumb": "/library/metadata/10/thumb",
                "grandparentArt": "/library/metadata/10/art",
            },
        ]
    }
}

PLEX_BASE = "http://host.docker.internal:32400"


def _create_test_app():
    """Create a test app with http_client set directly (no lifespan needed)."""
    test_app = FastAPI()

    @test_app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    test_app.include_router(webhook.router)
    test_app.include_router(proxy.router)

    # Set the http_client on state directly
    test_app.state.http_client = httpx.AsyncClient(
        base_url=PLEX_BASE,
        timeout=30.0,
    )
    return test_app


@pytest.mark.asyncio
async def test_health_endpoint():
    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_proxy_passthrough_non_episode_route():
    """Non-episode routes are forwarded unchanged."""
    test_app = _create_test_app()

    with respx.mock:
        respx.get(f"{PLEX_BASE}/identity").mock(
            return_value=HttpxResponse(200, text="<MediaContainer machineIdentifier='abc123'/>")
        )

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/identity")
            assert resp.status_code == 200
            assert "abc123" in resp.text


@pytest.mark.asyncio
async def test_proxy_obscures_unwatched_xml():
    """Unwatched episodes in XML responses are obscured."""
    test_app = _create_test_app()

    with respx.mock:
        respx.get(f"{PLEX_BASE}/library/metadata/100/children").mock(
            return_value=HttpxResponse(
                200,
                content=PLEX_XML_EPISODES.encode(),
                headers={"content-type": "text/xml;charset=utf-8"},
            )
        )

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/library/metadata/100/children")
            assert resp.status_code == 200

            root = ET.fromstring(resp.content)
            episodes = [v for v in root.iter("Video") if v.get("type") == "episode"]

            assert episodes[0].get("title") == "Episode 1"
            assert episodes[0].get("summary") == ""
            assert episodes[0].get("thumb") == "/library/metadata/50/thumb"
            assert episodes[0].findall("Role") == []
            assert episodes[1].get("title") == "Episode 2"


@pytest.mark.asyncio
async def test_proxy_reveals_watched_xml():
    """After marking an episode watched, it passes through unmodified."""
    test_app = _create_test_app()

    with respx.mock:
        respx.get(f"{PLEX_BASE}/library/metadata/100/children").mock(
            return_value=HttpxResponse(
                200,
                content=PLEX_XML_EPISODES.encode(),
                headers={"content-type": "text/xml;charset=utf-8"},
            )
        )

        await mark_watched("301")

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/library/metadata/100/children")
            root = ET.fromstring(resp.content)
            episodes = [v for v in root.iter("Video") if v.get("type") == "episode"]

            assert episodes[0].get("title") == "Winter Is Coming"
            assert episodes[0].get("summary") == "Ned Stark is asked to serve as Hand of the King."
            assert episodes[1].get("title") == "Episode 2"


@pytest.mark.asyncio
async def test_proxy_obscures_unwatched_json():
    """Unwatched episodes in JSON responses are obscured."""
    test_app = _create_test_app()

    with respx.mock:
        respx.get(f"{PLEX_BASE}/library/metadata/100/children").mock(
            return_value=HttpxResponse(
                200,
                content=json.dumps(PLEX_JSON_EPISODES).encode(),
                headers={"content-type": "application/json"},
            )
        )

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/library/metadata/100/children")
            assert resp.status_code == 200

            data = resp.json()
            eps = data["MediaContainer"]["Metadata"]

            assert eps[0]["title"] == "Episode 1"
            assert eps[0]["summary"] == ""
            assert eps[0]["thumb"] == "/library/metadata/50/thumb"
            assert "Role" not in eps[0]
            assert eps[1]["title"] == "Episode 2"


@pytest.mark.asyncio
async def test_proxy_reveals_after_webhook():
    """Full flow: webhook marks episode watched, then proxy reveals it."""
    test_app = _create_test_app()

    with respx.mock:
        respx.get(f"{PLEX_BASE}/library/metadata/100/children").mock(
            return_value=HttpxResponse(
                200,
                content=json.dumps(PLEX_JSON_EPISODES).encode(),
                headers={"content-type": "application/json"},
            )
        )

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First request — both obscured
            resp1 = await client.get("/library/metadata/100/children")
            data1 = resp1.json()
            assert data1["MediaContainer"]["Metadata"][0]["title"] == "Episode 1"

            # Webhook fires for episode 301
            webhook_payload = {
                "event": "media.scrobble",
                "Metadata": {
                    "type": "episode",
                    "ratingKey": "301",
                    "grandparentTitle": "GoT",
                    "parentIndex": 1,
                    "index": 1,
                },
            }
            await client.post(
                "/webhook/plex",
                data={"payload": json.dumps(webhook_payload)},
            )

            # Second request — 301 revealed, 302 still obscured
            resp2 = await client.get("/library/metadata/100/children")
            data2 = resp2.json()
            eps = data2["MediaContainer"]["Metadata"]
            assert eps[0]["title"] == "Winter Is Coming"
            assert eps[0]["summary"] == "Ned Stark is asked to serve as Hand of the King."
            assert eps[1]["title"] == "Episode 2"
            assert eps[1]["summary"] == ""


@pytest.mark.asyncio
async def test_proxy_handles_upstream_error():
    """Upstream errors are forwarded to the client."""
    test_app = _create_test_app()

    with respx.mock:
        respx.get(f"{PLEX_BASE}/library/metadata/999").mock(
            return_value=HttpxResponse(404, text="Not Found")
        )

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/library/metadata/999")
            assert resp.status_code == 404
