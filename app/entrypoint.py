"""Entrypoint that launches uvicorn with optional SSL."""

import uvicorn

from app.config import settings


def main():
    ssl_kwargs = {}
    if settings.ssl_certfile and settings.ssl_keyfile:
        ssl_kwargs["ssl_certfile"] = settings.ssl_certfile
        ssl_kwargs["ssl_keyfile"] = settings.ssl_keyfile

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.proxy_port,
        log_level=settings.log_level,
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
