"""Tests for Plex API write operations."""

from unittest.mock import patch

import httpx
import pytest
import respx
from httpx import Response as HttpxResponse

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


def _client():
    return httpx.AsyncClient(base_url=PLEX_BASE, timeout=5.0)


def _obscure_req(**overrides):
    defaults = {
        "section_key": "1",
        "rating_key": "101",
        "episode_index": 1,
        "parent_thumb": "/library/metadata/50/thumb",
        "grandparent_thumb": "/library/metadata/10/thumb",
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
        "original_thumb": "/library/metadata/101/thumb",
    }
    defaults.update(overrides)
    return RestoreRequest(**defaults)


@pytest.mark.asyncio
async def test_obscure_episode_sends_correct_params():
    async with _client() as client:
        with respx.mock:
            route = respx.put(f"{PLEX_BASE}/library/sections/1/all").mock(
                return_value=HttpxResponse(200)
            )
            poster_route = respx.put(f"{PLEX_BASE}/library/metadata/101/poster").mock(
                return_value=HttpxResponse(200)
            )

            result = await obscure_episode(client, _obscure_req())

            assert result is True
            assert route.called
            request = route.calls[0].request
            url_str = str(request.url)
            assert "title.value=Episode+1" in url_str or "title.value=Episode%201" in url_str
            assert "title.locked=1" in url_str
            assert "summary.value=" in url_str
            assert "summary.locked=1" in url_str
            assert "thumb.locked=1" in url_str
            # Poster set via separate endpoint, not thumb.value
            assert "thumb.value=" not in url_str
            assert poster_route.called
            poster_url = str(poster_route.calls[0].request.url)
            assert "url=%2Flibrary%2Fmetadata%2F50%2Fthumb" in poster_url


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
            refresh_route = respx.put(f"{PLEX_BASE}/library/metadata/101/refresh").mock(
                return_value=HttpxResponse(200)
            )

            result = await restore_episode(client, _restore_req())

            assert result is True
            assert put_route.called
            assert refresh_route.called
            request = put_route.calls[0].request
            url_str = str(request.url)
            assert "title.locked=0" in url_str
            assert "summary.locked=0" in url_str


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
            respx.put(url__regex=r".*/poster").mock(
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
                poster_route = respx.put(url__regex=r".*/poster").mock(
                    return_value=HttpxResponse(200)
                )

                await obscure_episode(client, _obscure_req())

                url_str = str(route.calls[0].request.url)
                assert "title.value=" in url_str
                assert "summary.value=" not in url_str
                assert "thumb.locked=" not in url_str
                # No poster call when thumbnail disabled
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
                poster_route = respx.put(url__regex=r".*/poster").mock(
                    return_value=HttpxResponse(200)
                )

                await obscure_episode(client, _obscure_req())

                url_str = str(route.calls[0].request.url)
                # Only type and id should be present
                assert "title.value=" not in url_str
                assert "summary.value=" not in url_str
                assert "thumb.locked=" not in url_str
                assert not poster_route.called
