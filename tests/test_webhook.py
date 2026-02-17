import json

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.services.watch_state import is_watched


def _create_test_app():
    """Create a fresh app without the sync lifespan."""
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from app.database import init_db
    from app.routers import proxy, webhook

    @asynccontextmanager
    async def test_lifespan(app: FastAPI):
        await init_db()
        app.state.http_client = httpx.AsyncClient(
            base_url="http://host.docker.internal:32400",
            timeout=30.0,
        )
        yield
        await app.state.http_client.aclose()

    test_app = FastAPI(lifespan=test_lifespan)
    test_app.include_router(webhook.router)
    test_app.include_router(proxy.router)
    return test_app


def _scrobble_payload(rating_key: str = "101", media_type: str = "episode") -> dict:
    return {
        "event": "media.scrobble",
        "Metadata": {
            "type": media_type,
            "ratingKey": rating_key,
            "grandparentTitle": "Friends",
            "parentIndex": 2,
            "index": 5,
        },
    }


@pytest.mark.asyncio
async def test_scrobble_marks_episode_watched():
    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert await is_watched("101") is False

        resp = await client.post(
            "/webhook/plex",
            data={"payload": json.dumps(_scrobble_payload("101"))},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"
        assert await is_watched("101") is True


@pytest.mark.asyncio
async def test_non_episode_scrobble_is_ignored():
    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhook/plex",
            data={"payload": json.dumps(_scrobble_payload("200", media_type="movie"))},
        )
        assert resp.status_code == 200
        assert await is_watched("200") is False


@pytest.mark.asyncio
async def test_non_scrobble_event_is_ignored():
    payload = {"event": "media.play", "Metadata": {"type": "episode", "ratingKey": "101"}}
    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhook/plex",
            data={"payload": json.dumps(payload)},
        )
        assert resp.status_code == 200
        assert await is_watched("101") is False


@pytest.mark.asyncio
async def test_missing_payload_returns_ignored():
    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/webhook/plex", data={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_malformed_payload_does_not_crash():
    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhook/plex",
            data={"payload": "not-valid-json"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"
