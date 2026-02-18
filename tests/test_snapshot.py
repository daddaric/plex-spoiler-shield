"""Tests for metadata snapshot CRUD operations."""

import pytest

from app.services.snapshot import (
    get_all_obscured,
    get_obscured_for_keys,
    get_snapshot,
    mark_obscured,
    mark_restored,
    save_snapshots_batch,
)


def _make_snapshot(rating_key="101", section_key="1", **overrides):
    base = {
        "rating_key": rating_key,
        "section_key": section_key,
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
async def test_save_and_get_snapshot():
    await save_snapshots_batch([_make_snapshot()])
    snap = await get_snapshot("101")
    assert snap is not None
    assert snap.rating_key == "101"
    assert snap.section_key == "1"
    assert snap.original_title == "Winter Is Coming"
    assert snap.original_summary == "Ned Stark is asked to serve."
    assert snap.original_tagline == "A big reveal"
    assert snap.original_thumb == "/library/metadata/101/thumb"
    assert snap.episode_index == 1
    assert snap.obscured is False


@pytest.mark.asyncio
async def test_get_snapshot_nonexistent():
    snap = await get_snapshot("99999")
    assert snap is None


@pytest.mark.asyncio
async def test_save_batch_multiple():
    snapshots = [
        _make_snapshot("101"),
        _make_snapshot("102", title="The Kingsroad", episode_index=2),
    ]
    await save_snapshots_batch(snapshots)
    s1 = await get_snapshot("101")
    s2 = await get_snapshot("102")
    assert s1 is not None
    assert s2 is not None
    assert s1.original_title == "Winter Is Coming"
    assert s2.original_title == "The Kingsroad"


@pytest.mark.asyncio
async def test_save_batch_empty():
    await save_snapshots_batch([])  # should not raise


@pytest.mark.asyncio
async def test_upsert_updates_when_not_obscured():
    await save_snapshots_batch([_make_snapshot("101", title="Original")])
    await save_snapshots_batch([_make_snapshot("101", title="Updated")])
    snap = await get_snapshot("101")
    assert snap.original_title == "Updated"


@pytest.mark.asyncio
async def test_upsert_does_not_overwrite_originals_when_obscured():
    """Critical safety test: if episode is obscured, original_* fields
    should NOT be overwritten (they'd contain obscured values)."""
    await save_snapshots_batch([_make_snapshot("101", title="Real Title")])
    await mark_obscured("101")

    # Now try to save again with obscured values
    await save_snapshots_batch([_make_snapshot("101", title="Episode 1", summary="")])

    snap = await get_snapshot("101")
    assert snap.original_title == "Real Title"
    assert snap.original_summary == "Ned Stark is asked to serve."
    assert snap.obscured is True


@pytest.mark.asyncio
async def test_mark_obscured():
    await save_snapshots_batch([_make_snapshot("101")])
    await mark_obscured("101")
    snap = await get_snapshot("101")
    assert snap.obscured is True


@pytest.mark.asyncio
async def test_mark_restored():
    await save_snapshots_batch([_make_snapshot("101")])
    await mark_obscured("101")
    await mark_restored("101")
    snap = await get_snapshot("101")
    assert snap.obscured is False


@pytest.mark.asyncio
async def test_get_all_obscured():
    await save_snapshots_batch([
        _make_snapshot("101"),
        _make_snapshot("102"),
        _make_snapshot("103"),
    ])
    await mark_obscured("101")
    await mark_obscured("103")

    obscured = await get_all_obscured()
    keys = {s.rating_key for s in obscured}
    assert keys == {"101", "103"}


@pytest.mark.asyncio
async def test_get_obscured_for_keys():
    await save_snapshots_batch([
        _make_snapshot("101"),
        _make_snapshot("102"),
        _make_snapshot("103"),
    ])
    await mark_obscured("101")
    await mark_obscured("102")

    result = await get_obscured_for_keys(["101", "103"])
    assert "101" in result
    assert "103" not in result


@pytest.mark.asyncio
async def test_get_obscured_for_keys_empty():
    result = await get_obscured_for_keys([])
    assert result == {}
