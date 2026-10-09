"""The bucket layout, on any S3-compatible store (the prefix is empty by default, so pages sit
at the bucket root):

    <prefix><name>/current                   the current version id, as text
    <prefix><name>/visibility                private, ontic or public (absent means ontic)
    <prefix><name>/comments.json             the comments, written by the gateway (comments.py)
    <prefix><name>/<version>/page.json       metadata of that version
    <prefix><name>/<version>/<files...>      the page itself

Versions are UTC timestamps (20261007T153000Z), so they sort by time. Nothing here deletes.
"""

from __future__ import annotations

import json
import mimetypes
import re

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from .config import Config

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
# New names must also work as a host name, since each page is served from <name>.<suffix>:
# no underscores, and dot-separated parts that start and end with a letter or digit.
HOST_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")
VERSION_RE = re.compile(r"^\d{8}T\d{6}Z$")
VISIBILITIES = ("private", "ontic", "public")
DEFAULT_VISIBILITY = "ontic"
# Path segments the gateway uses for itself, so no page may take them as its name.
RESERVED_NAMES = {"public", "oauth2", "_info", "_health", "page.json"}

# Types mimetypes gets wrong or does not know on some systems.
EXTRA_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".md": "text/markdown",
}


def content_type(path: str) -> str:
    ext = path[path.rfind(".") :].lower() if "." in path.rsplit("/", 1)[-1] else ""
    ctype = EXTRA_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/json", "image/svg+xml"):
        ctype += "; charset=utf-8"
    return ctype


def check_name(name: str) -> str:
    if not NAME_RE.match(name) or not HOST_NAME_RE.match(name) or name in RESERVED_NAMES:
        raise ValueError(
            f"bad page name {name!r}: use lowercase letters, digits, '.' or '-' "
            "(up to 64 characters, starting and ending with a letter or digit; "
            "not public, oauth2 or page.json)"
        )
    return name


def check_visibility(level: str) -> str:
    if level not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {', '.join(VISIBILITIES)}, got {level!r}")
    return level


def make_client(cfg: Config):
    kwargs = {}
    if cfg.access_key_id and cfg.secret_access_key:
        kwargs = {
            "aws_access_key_id": cfg.access_key_id,
            "aws_secret_access_key": cfg.secret_access_key,
        }
    # s3v4 for the presigned upload URLs too (B2 takes only that), signed for cfg.region.
    return boto3.client(
        "s3", endpoint_url=cfg.endpoint, region_name=cfg.region,
        config=BotoConfig(signature_version="s3v4"), **kwargs,
    )  # fmt: skip


def is_missing(err: ClientError) -> bool:
    return err.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound")


class Store:
    def __init__(self, client, bucket: str, prefix: str = ""):
        if not bucket:
            raise SystemExit("no bucket configured: set ONTIC_PAGES_BUCKET (see README)")
        self.client, self.bucket, self.prefix = client, bucket, prefix

    def key(self, *parts: str) -> str:
        return self.prefix + "/".join(parts)

    def put(self, key: str, body) -> None:
        """Body is bytes or an open binary file."""
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType=content_type(key)
        )

    def get(self, key: str, range_header: str | None = None) -> dict | None:
        """The raw get_object response, or None when the key does not exist."""
        kwargs = {"Range": range_header} if range_header else {}
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key, **kwargs)
        except ClientError as err:
            if is_missing(err):
                return None
            raise

    def presign_put(self, key: str, seconds: int = 3600) -> tuple[str, dict[str, str]]:
        """A URL that lets its holder PUT this one key for `seconds`, and the headers to send
        with it (the content type is signed, so the upload must carry exactly that one)."""
        ctype = content_type(key)
        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": ctype},
            ExpiresIn=seconds,
        )
        return url, {"Content-Type": ctype}

    def presign_get(self, key: str, seconds: int = 3600) -> str:
        """A URL that lets its holder GET this one key for `seconds`."""
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=seconds
        )

    def copy(self, src: str, dst: str) -> None:
        """A server-side copy within the bucket (the bytes stay in the store), with its type."""
        self.client.copy_object(
            Bucket=self.bucket, Key=dst, CopySource={"Bucket": self.bucket, "Key": src}
        )

    def sizes(self, prefix: str) -> dict[str, int]:
        """Key (below prefix) -> size, for every object under prefix."""
        out, token = {}, None
        while True:
            kwargs = {"ContinuationToken": token} if token else {}
            resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix, **kwargs)
            for obj in resp.get("Contents", []):
                out[obj["Key"][len(prefix) :]] = obj["Size"]
            if not resp.get("IsTruncated"):
                return out
            token = resp["NextContinuationToken"]

    def read_text(self, key: str) -> str | None:
        obj = self.get(key)
        return None if obj is None else obj["Body"].read().decode()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as err:
            if is_missing(err):
                return False
            raise

    def _children(self, prefix: str) -> list[str]:
        """Names one level below a prefix (like `ls`), without the trailing slash."""
        out, token = [], None
        while True:
            kwargs = {"ContinuationToken": token} if token else {}
            resp = self.client.list_objects_v2(
                Bucket=self.bucket, Prefix=prefix, Delimiter="/", **kwargs
            )
            out += [p["Prefix"][len(prefix) :].rstrip("/") for p in resp.get("CommonPrefixes", [])]
            if not resp.get("IsTruncated"):
                return sorted(out)
            token = resp["NextContinuationToken"]

    def names(self) -> list[str]:
        return [n for n in self._children(self.prefix) if NAME_RE.match(n)]

    def versions(self, name: str) -> list[str]:
        return [v for v in self._children(self.key(name) + "/") if VERSION_RE.match(v)]

    def current(self, name: str) -> str | None:
        text = self.read_text(self.key(name, "current"))
        return text.strip() if text else None

    def set_current(self, name: str, version: str) -> None:
        self.put(self.key(name, "current"), version.encode())

    def visibility(self, name: str) -> str:
        """The page's level; absent means ontic, anything unreadable means private."""
        text = self.read_text(self.key(name, "visibility"))
        if text is None:
            return DEFAULT_VISIBILITY
        level = text.strip()
        return level if level in VISIBILITIES else "private"

    def set_visibility(self, name: str, level: str) -> None:
        self.put(self.key(name, "visibility"), check_visibility(level).encode())

    def meta(self, name: str, version: str) -> dict:
        text = self.read_text(self.key(name, version, "page.json"))
        return json.loads(text) if text else {}
