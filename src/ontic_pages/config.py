"""Where the pages live: bucket, endpoint, credentials and the public URL.

Read from ~/.config/ontic-pages/config.toml, then overridden by environment variables:

    bucket            ONTIC_PAGES_BUCKET
    endpoint          ONTIC_PAGES_ENDPOINT
    region            ONTIC_PAGES_REGION
    prefix            ONTIC_PAGES_PREFIX     (default "pages/")
    url               ONTIC_PAGES_URL        (default "https://pages.onticlabs.io")
    access_key_id     AWS_ACCESS_KEY_ID
    secret_access_key AWS_SECRET_ACCESS_KEY

Credentials left unset fall through to boto3's own lookup (AWS_PROFILE, ~/.aws).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PREFIX = "pages/"
DEFAULT_URL = "https://pages.onticlabs.io"

ENV = {
    "bucket": "ONTIC_PAGES_BUCKET",
    "endpoint": "ONTIC_PAGES_ENDPOINT",
    "region": "ONTIC_PAGES_REGION",
    "prefix": "ONTIC_PAGES_PREFIX",
    "url": "ONTIC_PAGES_URL",
    "access_key_id": "AWS_ACCESS_KEY_ID",
    "secret_access_key": "AWS_SECRET_ACCESS_KEY",
}


@dataclass(frozen=True)
class Config:
    bucket: str | None = None
    endpoint: str | None = None
    region: str | None = None
    prefix: str = DEFAULT_PREFIX
    url: str = DEFAULT_URL
    access_key_id: str | None = None
    secret_access_key: str | None = None

    def page_url(self, name: str) -> str:
        return f"{self.url.rstrip('/')}/{name}/"


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "ontic-pages" / "config.toml"


def load_config(path: Path | None = None, env: dict[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    path = path or config_path()
    values: dict[str, str] = {}
    if path.exists():
        data = tomllib.loads(path.read_text())
        unknown = set(data) - set(ENV)
        if unknown:
            raise SystemExit(f"{path}: unknown keys {sorted(unknown)}")
        values = {k: str(v) for k, v in data.items()}
    for key, var in ENV.items():
        if env.get(var):
            values[key] = env[var]
    if "prefix" in values:
        values["prefix"] = values["prefix"].strip("/") + "/" if values["prefix"].strip("/") else ""
    return Config(**values)
