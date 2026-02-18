import os
import tempfile
from unittest.mock import patch

import pytest
import pytest_asyncio
import aiosqlite

# Patch DB_PATH before importing any app modules
_tmp_dir = tempfile.mkdtemp()
_test_db_path = os.path.join(_tmp_dir, "test_watch_state.db")

# Patch at the settings level and all modules that read DB_PATH at import time
_patches = [
    patch("app.config.settings.db_path", _test_db_path),
    patch("app.database.DB_PATH", _test_db_path),
    patch("app.services.watch_state.DB_PATH", _test_db_path),
    patch("app.services.snapshot.DB_PATH", _test_db_path),
]

for p in _patches:
    p.start()

from app.database import init_db  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    """Create schema before each test and clear data after."""
    await init_db()
    yield
    # Clear data between tests instead of deleting file (avoids Windows locking issues)
    async with aiosqlite.connect(_test_db_path) as db:
        await db.execute("DELETE FROM watch_state")
        await db.execute("DELETE FROM metadata_snapshot")
        await db.commit()
