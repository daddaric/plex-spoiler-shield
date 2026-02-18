"""Tests for restore and status endpoints."""

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response as HttpxResponse
from fastapi import FastAPI

from app.routers import restore, webhook
from app.services.snapshot import mark_obscured, save_snapshots_batch


PLEX_BASE = "http://plex:32400"


def _create_test_app():
    test_app = FastAPI()

    @test_app.get("/health")
    async def health():
        return {"status": "ok"}

    test_app.include_router(restore.router)
    test_app.include_router(webhook.router)

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
        "tagline": "A big reveal",
        "thumb": "/library/metadata/101/thumb",
        "episode_index": 1,
        "parent_thumb": "/library/metadata/50/thumb",
        "grandparent_thumb": "/library/metadata/10/thumb",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_status_no_obscured():
    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["obscured_count"] == 0
        assert data["episodes"] == []


@pytest.mark.asyncio
async def test_status_with_obscured():
    await save_snapshots_batch([_make_snapshot("101"), _make_snapshot("102")])
    await mark_obscured("101")

    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")
        data = resp.json()
        assert data["obscured_count"] == 1
        assert data["episodes"][0]["rating_key"] == "101"


@pytest.mark.asyncio
async def test_restore_all_no_obscured():
    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/restore/all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["restored"] == 0


@pytest.mark.asyncio
async def test_restore_all_restores_obscured():
    await save_snapshots_batch([_make_snapshot("101"), _make_snapshot("102")])
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
            resp = await client.post("/restore/all")
            data = resp.json()
            assert data["restored"] == 2
            assert data["failed"] == 0

            # Verify status shows none obscured
            status_resp = await client.get("/status")
            assert status_resp.json()["obscured_count"] == 0
