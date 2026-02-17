import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    plex_url: str = "http://host.docker.internal:32400"
    plex_token: str = ""
    proxy_port: int = 32401
    db_path: str = "/data/watch_state.db"
    poll_interval: int = 600
    log_level: str = "info"
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    config_path: str = "config.yml"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@dataclass
class ObfuscationConfig:
    title: bool = True
    summary: bool = True
    thumbnail: bool = True
    roles: bool = True


@dataclass
class AppConfig:
    protected_libraries: list[str] = field(default_factory=list)
    obfuscation: ObfuscationConfig = field(default_factory=ObfuscationConfig)
    title_template: str = "Episode {n}"


def load_app_config(path: str) -> AppConfig:
    config_file = Path(path)
    if not config_file.exists():
        return AppConfig()

    with open(config_file) as f:
        raw = yaml.safe_load(f) or {}

    obf_raw = raw.get("obfuscation", {})
    obfuscation = ObfuscationConfig(
        title=obf_raw.get("title", True),
        summary=obf_raw.get("summary", True),
        thumbnail=obf_raw.get("thumbnail", True),
        roles=obf_raw.get("roles", True),
    )

    return AppConfig(
        protected_libraries=raw.get("protected_libraries", []),
        obfuscation=obfuscation,
        title_template=raw.get("title_template", "Episode {n}"),
    )


settings = Settings()
app_config = load_app_config(settings.config_path)
