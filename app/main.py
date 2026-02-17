import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

from app.config import settings
from app.database import init_db
from app.routers import proxy, webhook
from app.services.sync import initial_sync, poll_loop

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("plex-spoiler-shield")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initialising database...")
    await init_db()
    logger.info("Database ready.")

    app.state.http_client = httpx.AsyncClient(
        base_url=settings.plex_url,
        timeout=30.0,
    )
    logger.info(f"Proxy targeting Plex at {settings.plex_url}")

    # Run initial full-library sync
    await initial_sync(app.state.http_client)

    # Start background poll loop
    poll_task = asyncio.create_task(poll_loop(app.state.http_client))

    yield

    # Shutdown
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass
    await app.state.http_client.aclose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Plex Spoiler Shield",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook.router)
app.include_router(proxy.router)  # catch-all, must be last


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
