"""End-to-end tests: sync flow with mocked Plex upstream."""

import json

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response as HttpxResponse
from fastapi import FastAPI

from app.routers import restore, webhook
from app.services.snapshot import get_all_obscured, get_snapshot, save_snapshots_batch, mark_obscured
from app.services.watch_state import mark_watched


PLEX_BASE = "http://plex:32400"


def _create_test_app():
    """Create a test app with http_client set directly (no lifespan needed)."""
    test_app = FastAPI()

    @test_app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.2.0"}

    test_app.include_router(webhook.router)
    test_app.include_router(restore.router)

    test_app.state.http_client = httpx.AsyncClient(
        base_url=PLEX_BASE,
        timeout=5.0,
    )
    return test_app


def _make_snapshot(rating_key="101", **overrides):
    base = {
        "rating_key": rating_key,
        "section_key": "1",
        "title": "Winter Is Coming",
        "summary": "Ned Stark is asked to serve.",
        "tagline": "",
        "thumb": f"/library/metadata/{rating_key}/thumb",
        "episode_index": 1,
        "parent_thumb": "/library/metadata/50/thumb",
        "grandparent_thumb": "/library/metadata/10/thumb",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_health_endpoint():
    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_scrobble_restores_obscured_episode():
    """Full flow: episode is obscured, webhook fires, metadata is restored."""
    # Set up: snapshot exists and is marked obscured
    await save_snapshots_batch([_make_snapshot("301")])
    await mark_obscured("301")

    test_app = _create_test_app()

    with respx.mock:
        put_route = respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
            return_value=HttpxResponse(200)
        )
        respx.put(f"{PLEX_BASE}/library/metadata/301/refresh").mock(
            return_value=HttpxResponse(200)
        )

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
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
            resp = await client.post(
                "/webhook/plex",
                data={"payload": json.dumps(webhook_payload)},
            )
            assert resp.status_code == 200

        # Verify the episode is no longer obscured
        snap = await get_snapshot("301")
        assert snap.obscured is False

        # Verify Plex API was called with restore params
        assert put_route.called
        url_str = str(put_route.calls[0].request.url)
        assert "title.locked=0" in url_str


@pytest.mark.asyncio
async def test_webhook_scrobble_no_snapshot_still_marks_watched():
    """Webhook for an episode without a snapshot still marks it watched."""
    test_app = _create_test_app()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        webhook_payload = {
            "event": "media.scrobble",
            "Metadata": {
                "type": "episode",
                "ratingKey": "999",
                "grandparentTitle": "Unknown",
                "parentIndex": 1,
                "index": 1,
            },
        }
        resp = await client.post(
            "/webhook/plex",
            data={"payload": json.dumps(webhook_payload)},
        )
        assert resp.status_code == 200

    from app.services.watch_state import is_watched
    assert await is_watched("999") is True


@pytest.mark.asyncio
async def test_status_then_restore_all_flow():
    """Check status, restore all, verify status is clear."""
    await save_snapshots_batch([
        _make_snapshot("101"),
        _make_snapshot("102", title="The Kingsroad", episode_index=2),
    ])
    await mark_obscured("101")
    await mark_obscured("102")

    test_app = _create_test_app()

    with respx.mock:
        respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
            return_value=HttpxResponse(200)
        )
        respx.put(url__regex=r".*/refresh$").mock(
            return_value=HttpxResponse(200)
        )

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Check status - 2 obscured
            status_resp = await client.get("/status")
            assert status_resp.json()["obscured_count"] == 2

            # Restore all
            restore_resp = await client.post("/restore/all")
            assert restore_resp.json()["restored"] == 2

            # Check status again - 0 obscured
            status_resp2 = await client.get("/status")
            assert status_resp2.json()["obscured_count"] == 0
