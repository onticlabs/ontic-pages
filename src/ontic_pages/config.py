"""Where the pages live: bucket, endpoint, credentials and the public URL.

Read from ~/.config/ontic-pages/config.toml, then overridden by environment variables:

    bucket            ONTIC_PAGES_BUCKET     (default "ontic-pages")
    endpoint          ONTIC_PAGES_ENDPOINT   (default Backblaze B2 eu-central-003)
    region            ONTIC_PAGES_REGION     (default "eu-central-003")
    prefix            ONTIC_PAGES_PREFIX     (default none: pages sit at the bucket root)
    url               ONTIC_PAGES_URL        (default "https://pages.onticlabs.io")
    email             ONTIC_PAGES_EMAIL      (who you are; default: git user.email, else $USER)
    access_key_id     AWS_ACCESS_KEY_ID
    secret_access_key AWS_SECRET_ACCESS_KEY

Credentials left unset fall through to boto3's own lookup (AWS_PROFILE, ~/.aws).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PREFIX = ""
DEFAULT_BUCKET = "ontic-pages"
DEFAULT_ENDPOINT = "https://s3.eu-central-003.backblazeb2.com"
DEFAULT_REGION = "eu-central-003"
DEFAULT_URL = "https://pages.onticlabs.io"

ENV = {
    "bucket": "ONTIC_PAGES_BUCKET",
    "endpoint": "ONTIC_PAGES_ENDPOINT",
    "region": "ONTIC_PAGES_REGION",
    "prefix": "ONTIC_PAGES_PREFIX",
    "url": "ONTIC_PAGES_URL",
    "email": "ONTIC_PAGES_EMAIL",
    "access_key_id": "AWS_ACCESS_KEY_ID",
    "secret_access_key": "AWS_SECRET_ACCESS_KEY",
}


@dataclass(frozen=True)
class Config:
    bucket: str = DEFAULT_BUCKET
    endpoint: str = DEFAULT_ENDPOINT
    region: str = DEFAULT_REGION
    prefix: str = DEFAULT_PREFIX
    url: str = DEFAULT_URL
    email: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None

    def page_url(self, name: str, public: bool = False) -> str:
        return f"{self.url.rstrip('/')}/{'public/' if public else ''}{name}/"


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
