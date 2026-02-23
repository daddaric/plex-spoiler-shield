"""Tests for restore and status endpoints."""

import io

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response as HttpxResponse
from fastapi import FastAPI
from PIL import Image

from app.routers import restore, webhook
from app.services.snapshot import mark_obscured, save_snapshots_batch


PLEX_BASE = "http://plex:32400"

POSTERS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer size="2">
  <Photo ratingKey="metadata://posters/tv.plex.agents.series_abc" provider="tmdb" selected="0"/>
  <Photo ratingKey="upload://posters/seasons/0/episodes/1/deadbeef" provider="" selected="1"/>
</MediaContainer>"""


def _make_jpeg(width: int = 4, height: int = 6) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(100, 100, 100)).save(buf, format="JPEG")
    return buf.getvalue()


FAKE_POSTER_BYTES = _make_jpeg()


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
        respx.get(url__regex=r".*/posters$").mock(
            return_value=HttpxResponse(200, content=POSTERS_XML, headers={"content-type": "text/xml"})
        )
        respx.put(url__regex=r".*/poster(?!s)").mock(
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


@pytest.mark.asyncio
async def test_reindex_thumbnails_no_obscured():
    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/reindex/thumbnails")
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 0
        assert "message" in data


@pytest.mark.asyncio
async def test_reindex_thumbnails_updates_obscured():
    await save_snapshots_batch([_make_snapshot("101"), _make_snapshot("102")])
    await mark_obscured("101")
    await mark_obscured("102")

    test_app = _create_test_app()

    with respx.mock:
        respx.get(url__regex=r".*/thumb").mock(
            return_value=HttpxResponse(200, content=FAKE_POSTER_BYTES)
        )
        respx.post(url__regex=r".*/posters$").mock(
            return_value=HttpxResponse(200)
        )

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/reindex/thumbnails")
            data = resp.json()
            assert data["updated"] == 2
            assert data["failed"] == 0
            assert data["skipped"] == 0


@pytest.mark.asyncio
async def test_reindex_thumbnails_skips_no_thumb():
    await save_snapshots_batch([_make_snapshot("101", parent_thumb=None, grandparent_thumb=None)])
    await mark_obscured("101")

    test_app = _create_test_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/reindex/thumbnails")
        data = resp.json()
        assert data["updated"] == 0
        assert data["skipped"] == 1
        assert data["failed"] == 0
