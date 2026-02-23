"""Tests for Plex API write operations."""

import io
from unittest.mock import patch

import httpx
import pytest
import respx
from httpx import Response as HttpxResponse
from PIL import Image

from app.config import ObfuscationConfig
from app.services.plex_writer import (
    ObscureRequest,
    RestoreRequest,
    obscure_episode,
    obscure_episodes_batch,
    restore_episode,
    restore_episodes_batch,
)

PLEX_BASE = "http://plex:32400"


def _make_jpeg(width: int = 4, height: int = 6) -> bytes:
    """Create a minimal portrait JPEG for testing."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(100, 100, 100)).save(buf, format="JPEG")
    return buf.getvalue()


FAKE_POSTER_BYTES = _make_jpeg()

POSTERS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer size="2">
  <Photo ratingKey="metadata://posters/tv.plex.agents.series_abc123" provider="tmdb" selected="0"/>
  <Photo ratingKey="upload://posters/seasons/0/episodes/1/deadbeef" provider="" selected="1"/>
</MediaContainer>"""


def _client():
    return httpx.AsyncClient(base_url=PLEX_BASE, timeout=5.0)


def _obscure_req(**overrides):
    defaults = {
        "section_key": "1",
        "rating_key": "101",
        "episode_index": 1,
        "parent_thumb": "/library/metadata/50/thumb/12345",
        "grandparent_thumb": "/library/metadata/10/thumb/12345",
    }
    defaults.update(overrides)
    return ObscureRequest(**defaults)


def _restore_req(**overrides):
    defaults = {
        "section_key": "1",
        "rating_key": "101",
        "original_title": "Winter Is Coming",
        "original_summary": "Ned Stark is asked to serve.",
        "original_tagline": "A big reveal",
        "original_thumb": "/library/metadata/101/thumb/12345",
    }
    defaults.update(overrides)
    return RestoreRequest(**defaults)


@pytest.mark.asyncio
async def test_obscure_episode_sends_correct_params():
    async with _client() as client:
        with respx.mock:
            sections_route = respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                return_value=HttpxResponse(200)
            )
            respx.get(f"{PLEX_BASE}/library/metadata/50/thumb/12345").mock(
                return_value=HttpxResponse(200, content=FAKE_POSTER_BYTES)
            )
            posters_route = respx.post(f"{PLEX_BASE}/library/metadata/101/posters").mock(
                return_value=HttpxResponse(200)
            )

            result = await obscure_episode(client, _obscure_req())

            assert result is True
            url_str = str(sections_route.calls[0].request.url)
            assert "title.value=Episode+1" in url_str or "title.value=Episode%201" in url_str
            assert "title.locked=1" in url_str
            assert "summary.value=" in url_str
            assert "summary.locked=1" in url_str
            assert "thumb.locked=1" in url_str
            # Poster set via binary upload, not thumb.value
            assert "thumb.value=" not in url_str
            assert posters_route.called


@pytest.mark.asyncio
async def test_obscure_uses_parent_thumb_as_poster():
    async with _client() as client:
        with respx.mock:
            respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                return_value=HttpxResponse(200)
            )
            # parent_thumb should be fetched first
            parent_fetch = respx.get(f"{PLEX_BASE}/library/metadata/50/thumb/12345").mock(
                return_value=HttpxResponse(200, content=FAKE_POSTER_BYTES)
            )
            grandparent_fetch = respx.get(f"{PLEX_BASE}/library/metadata/10/thumb/12345").mock(
                return_value=HttpxResponse(200, content=FAKE_POSTER_BYTES)
            )
            respx.post(f"{PLEX_BASE}/library/metadata/101/posters").mock(
                return_value=HttpxResponse(200)
            )

            await obscure_episode(client, _obscure_req())
            # parent_thumb takes priority
            assert parent_fetch.called
            assert not grandparent_fetch.called


@pytest.mark.asyncio
async def test_obscure_falls_back_to_grandparent_thumb():
    async with _client() as client:
        with respx.mock:
            respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                return_value=HttpxResponse(200)
            )
            grandparent_fetch = respx.get(f"{PLEX_BASE}/library/metadata/10/thumb/12345").mock(
                return_value=HttpxResponse(200, content=FAKE_POSTER_BYTES)
            )
            respx.post(f"{PLEX_BASE}/library/metadata/101/posters").mock(
                return_value=HttpxResponse(200)
            )

            await obscure_episode(client, _obscure_req(parent_thumb=None))
            assert grandparent_fetch.called


@pytest.mark.asyncio
async def test_obscure_episode_failure_returns_false():
    async with _client() as client:
        with respx.mock:
            respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                return_value=HttpxResponse(500)
            )

            result = await obscure_episode(client, _obscure_req())
            assert result is False


@pytest.mark.asyncio
async def test_restore_episode_sends_correct_params():
    async with _client() as client:
        with respx.mock:
            put_route = respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                return_value=HttpxResponse(200)
            )
            respx.get(f"{PLEX_BASE}/library/metadata/101/posters").mock(
                return_value=HttpxResponse(200, content=POSTERS_XML.encode(), headers={"content-type": "text/xml"})
            )
            poster_select = respx.put(f"{PLEX_BASE}/library/metadata/101/poster").mock(
                return_value=HttpxResponse(200)
            )
            refresh_route = respx.put(f"{PLEX_BASE}/library/metadata/101/refresh").mock(
                return_value=HttpxResponse(200)
            )

            result = await restore_episode(client, _restore_req())

            assert result is True
            url_str = str(put_route.calls[0].request.url)
            assert "title.locked=0" in url_str
            assert "summary.locked=0" in url_str
            assert "thumb.locked=0" in url_str
            # Agent poster should be selected (not the upload:// one)
            assert poster_select.called
            poster_url = str(poster_select.calls[0].request.url)
            assert "metadata%3A%2F%2Fposters" in poster_url or "metadata://" in poster_url
            assert refresh_route.called


@pytest.mark.asyncio
async def test_restore_episode_failure_returns_false():
    async with _client() as client:
        with respx.mock:
            respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                return_value=HttpxResponse(500)
            )

            result = await restore_episode(client, _restore_req())
            assert result is False


@pytest.mark.asyncio
async def test_obscure_batch():
    async with _client() as client:
        with respx.mock:
            respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                return_value=HttpxResponse(200)
            )
            respx.get(url__regex=r".*/thumb/.*").mock(
                return_value=HttpxResponse(200, content=FAKE_POSTER_BYTES)
            )
            respx.post(url__regex=r".*/posters$").mock(
                return_value=HttpxResponse(200)
            )

            reqs = [_obscure_req(rating_key="101"), _obscure_req(rating_key="102")]
            succeeded = await obscure_episodes_batch(client, reqs)
            assert set(succeeded) == {"101", "102"}


@pytest.mark.asyncio
async def test_restore_batch():
    async with _client() as client:
        with respx.mock:
            respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                return_value=HttpxResponse(200)
            )
            # GET /posters list for each episode
            respx.get(url__regex=r".*/posters$").mock(
                return_value=HttpxResponse(200, content=POSTERS_XML.encode(), headers={"content-type": "text/xml"})
            )
            # PUT /poster to select agent poster
            respx.put(url__regex=r"/library/metadata/\d+/poster(?!s)").mock(
                return_value=HttpxResponse(200)
            )
            respx.put(url__regex=r".*/refresh$").mock(
                return_value=HttpxResponse(200)
            )

            reqs = [_restore_req(rating_key="101"), _restore_req(rating_key="102")]
            succeeded = await restore_episodes_batch(client, reqs)
            assert set(succeeded) == {"101", "102"}


@pytest.mark.asyncio
async def test_obscure_respects_title_only_config():
    mock_obf = ObfuscationConfig(title=True, summary=False, thumbnail=False, roles=False)
    with patch("app.services.plex_writer.obf", mock_obf):
        async with _client() as client:
            with respx.mock:
                route = respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                    return_value=HttpxResponse(200)
                )
                poster_route = respx.post(url__regex=r".*/posters$").mock(
                    return_value=HttpxResponse(200)
                )

                await obscure_episode(client, _obscure_req())

                url_str = str(route.calls[0].request.url)
                assert "title.value=" in url_str
                assert "summary.value=" not in url_str
                assert "thumb.locked=" not in url_str
                assert not poster_route.called


@pytest.mark.asyncio
async def test_obscure_respects_all_disabled():
    mock_obf = ObfuscationConfig(title=False, summary=False, thumbnail=False, roles=False)
    with patch("app.services.plex_writer.obf", mock_obf):
        async with _client() as client:
            with respx.mock:
                route = respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                    return_value=HttpxResponse(200)
                )
                poster_route = respx.post(url__regex=r".*/posters$").mock(
                    return_value=HttpxResponse(200)
                )

                await obscure_episode(client, _obscure_req())

                url_str = str(route.calls[0].request.url)
                assert "title.value=" not in url_str
                assert "summary.value=" not in url_str
                assert "thumb.locked=" not in url_str
                assert not poster_route.called
