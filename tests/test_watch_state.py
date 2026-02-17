import pytest

from app.services.watch_state import (
    bulk_update,
    is_watched,
    is_watched_batch,
    mark_unwatched,
    mark_watched,
)


@pytest.mark.asyncio
async def test_unknown_key_is_unwatched():
    assert await is_watched("99999") is False


@pytest.mark.asyncio
async def test_mark_watched():
    await mark_watched("100")
    assert await is_watched("100") is True


@pytest.mark.asyncio
async def test_mark_unwatched():
    await mark_watched("100")
    await mark_unwatched("100")
    assert await is_watched("100") is False


@pytest.mark.asyncio
async def test_mark_watched_is_idempotent():
    await mark_watched("100")
    await mark_watched("100")
    assert await is_watched("100") is True


@pytest.mark.asyncio
async def test_is_watched_batch_mixed():
    await mark_watched("1")
    await mark_watched("3")
    result = await is_watched_batch(["1", "2", "3", "4"])
    assert result == {"1": True, "2": False, "3": True, "4": False}


@pytest.mark.asyncio
async def test_is_watched_batch_empty():
    result = await is_watched_batch([])
    assert result == {}


@pytest.mark.asyncio
async def test_bulk_update():
    items = [
        {"rating_key": "10", "watched": True},
        {"rating_key": "11", "watched": False},
        {"rating_key": "12", "watched": True},
    ]
    await bulk_update(items)
    assert await is_watched("10") is True
    assert await is_watched("11") is False
    assert await is_watched("12") is True


@pytest.mark.asyncio
async def test_bulk_update_overwrites():
    await mark_watched("10")
    await bulk_update([{"rating_key": "10", "watched": False}])
    assert await is_watched("10") is False


@pytest.mark.asyncio
async def test_bulk_update_empty():
    await bulk_update([])  # should not raise
