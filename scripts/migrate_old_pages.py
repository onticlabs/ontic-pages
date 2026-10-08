"""One-off: copy the old `ontic pages` (kind: page jobs) into the ontic-pages layout.

This script imports `ontic` (ontic-cli) because it READS THE OLD SYSTEM: the page jobs, their
records and manifests in the provenance store. That is the only place in this repo allowed to
import ontic; the package in src/ stays independent of ontic-cli. Run it with

    uv run --with /Users/mikel/OnticDev/cli scripts/migrate_old_pages.py --mapping out.json
    uv run --with /Users/mikel/OnticDev/cli scripts/migrate_old_pages.py --write --mapping out.json

Dry run (the default) reads the catalog and the store, prints one line per page and writes the
full mapping to --mapping. Nothing is written to any bucket. If --mapping already exists, its
names are kept (edit them there). --write reads the mapping back and copies

    <source bucket>/jobs/<job>/output/data/<path>  ->  <dest bucket>/<prefix><name>/<version>/<path>

then writes page.json for each version, then `visibility`, then `current`. Nothing is ever
deleted. A version whose page.json already exists is skipped, so --write can be re-run.

The source (ontic-r3) and the destination (ontic-pages) are different buckets and no key reads
both, so by default each file is read with the signed-in ontic session and uploaded with the
ontic-pages read-write key (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, or the key in
~/.config/ontic-pages/config.toml). When --source-bucket equals --dest-bucket, files are
copied server side (S3 CopyObject) instead.

Old layout (ontic-cli branch main-with-pages-and-viewer, src/ontic/pages/publish.py): a head
job's metadata has `page: {current, versions}`, a later version has `page: {of, version}`, and
a head never updated has no `page` key and is its own only version. Files live under
`output/data/` in each job's sealed manifest; `metadata.source_code` holds the git facts. The old
`--from` dependencies are not carried over. Old visibility maps to the new levels: private
stays private, team becomes ontic, public stays public.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ontic_pages.store import NAME_RE, RESERVED_NAMES, VISIBILITIES, content_type

DATA = "data/"
VISIBILITY = {"private": "private", "team": "ontic", "public": "public"}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", (text or "").lower())
    s = re.sub(r"-{2,}", "-", s).strip("-._")
    if len(s) > 64:  # cut at a word boundary
        cut = s[:65].rfind("-")
        s = s[: cut if cut > 20 else 64]
    return s.rstrip("-._")


def unique_name(base: str, taken: set[str]) -> str:
    name, n = base, 2
    while name in taken:
        suffix = f"-{n}"
        name = base[: 64 - len(suffix)].rstrip("-._") + suffix
        n += 1
    taken.add(name)
    return name


def version_id(timestamp: str, used: set[str]) -> str:
    t = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(UTC)
    t = t.replace(microsecond=0)
    while (v := t.strftime("%Y%m%dT%H%M%SZ")) in used:
        t += timedelta(seconds=1)
    used.add(v)
    return v


def to_git(source_code: dict | None) -> dict | None:
    if not isinstance(source_code, dict) or not source_code.get("commit"):
        return None
    return {
        "remote": source_code.get("repository"),
        "branch": source_code.get("branch"),
        "commit": source_code.get("commit"),
        "dirty": bool(source_code.get("dirty")),
    }


def page_block(metadata: dict) -> dict:
    block = metadata.get("page")
    return block if isinstance(block, dict) else {}


def version_ids(head: str, metadata: dict) -> list[str]:
    listed = page_block(metadata).get("versions")
    ids = [v for v in listed if isinstance(v, str) and v] if isinstance(listed, list) else []
    return ids if head in ids else [head, *ids]


# ---------------------------------------------------------------------------------------------
# Reading the old system (needs ontic)
# ---------------------------------------------------------------------------------------------


def page_heads(ctx) -> list[str]:
    from ontic.catalog_pages import iter_catalog_rows
    from ontic.catalog_types import CatalogQuery

    query = CatalogQuery(query_json=json.dumps({"kind": "page"}), limit=500)
    heads = []
    for row in iter_catalog_rows(ctx.catalog, query):
        try:
            metadata = json.loads(row.metadata_json)
        except (TypeError, ValueError):
            metadata = {}
        if not page_block(metadata if isinstance(metadata, dict) else {}).get("of"):
            heads.append(row.id)
    return list(dict.fromkeys(heads))


def read_version(store, job_id: str) -> dict:
    """Record, metadata and output files of one version job."""
    import yaml
    from ontic.job_records import load_job_record

    r3, metadata = load_job_record(store, job_id)
    manifest = yaml.safe_load(store.get(f"jobs/{job_id}/output/manifest.yaml")) or {}
    files = manifest.get("files") or {}
    sizes = manifest.get("sizes") or {}
    data = {}
    for rel in sorted(files):
        if rel.startswith(DATA):
            size = sizes.get(rel)
            if size is None:
                size = store.get_size(f"jobs/{job_id}/output/{rel}")
            data[rel[len(DATA) :]] = int(size)
    other = [rel for rel in files if not rel.startswith(DATA)]
    return {"r3": r3 or {}, "metadata": metadata or {}, "files": data, "other": other}


def plan(ctx, keep_names: dict[str, str] | None = None) -> tuple[list[dict], list[str]]:
    """Every old page and its versions. `keep_names` (head id -> name, from an earlier
    mapping) wins over the name made from the description."""
    store = ctx.store
    keep_names = keep_names or {}
    taken: set[str] = set()
    problems: list[str] = []
    pages = []
    heads = page_heads(ctx)
    records = {}
    for head in heads:
        try:
            records[head] = read_version(store, head)
        except Exception as exc:  # noqa: BLE001 - report and go on
            problems.append(f"{head}: head unreadable: {exc}")
    heads = sorted(records, key=lambda h: records[h]["r3"].get("timestamp", ""))
    for head in heads:
        meta = records[head]["metadata"]
        visibility = meta.get("visibility") or "private"
        current_job = page_block(meta).get("current") or head
        base = keep_names.get(head) or slug(meta.get("description", "")) or head[:8]
        if not NAME_RE.match(base) or base in RESERVED_NAMES:
            problems.append(f"{head}: name {base!r} is not allowed, using {head[:8]!r}")
            base = head[:8]
        name = unique_name(base, taken)
        if name != base:
            problems.append(f"{head}: name {base!r} taken, using {name!r}")
        used: set[str] = set()
        versions = []
        for job in version_ids(head, meta):
            try:
                rec = records[job] if job == head else read_version(store, job)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{head}: version {job} unreadable: {exc}")
                continue
            vmeta, r3 = rec["metadata"], rec["r3"]
            if not r3.get("timestamp"):
                problems.append(f"{head}: version {job} has no timestamp, skipped")
                continue
            version = version_id(r3["timestamp"], used)
            files = rec["files"]
            if "index.html" not in files:
                problems.append(f"{name}: version {version} ({job}) has no index.html")
            for reserved in ("page.json", "_info"):
                if reserved in files:
                    problems.append(f"{name}: version {version} has a top-level {reserved}")
            if rec["other"]:
                problems.append(f"{name}: {job} has files outside data/: {rec['other'][:3]}")
            if not files:
                problems.append(f"{name}: version {version} ({job}) has no files, skipped")
                continue
            page = {
                "name": name,
                "version": version,
                "published_at": datetime.strptime(version, "%Y%m%dT%H%M%SZ")
                .replace(tzinfo=UTC)
                .isoformat(),
                "published_by": vmeta.get("owner") or "",
                "description": vmeta.get("description") or "",
                "meta": {
                    "old_job_id": job,
                    "old_head_id": head,
                    "old_visibility": visibility,
                    "project": vmeta.get("project") or "",
                },
                "git": to_git(vmeta.get("source_code")),
                "files": len(files),
            }
            versions.append({"version": version, "job": job, "files": files, "page": page})
        if not versions:
            problems.append(f"{head}: no usable versions, page skipped")
            continue
        current = next((v["version"] for v in versions if v["job"] == current_job), None)
        if current is None:
            problems.append(f"{name}: current job {current_job} not among versions; using newest")
            current = versions[-1]["version"]
        pages.append(
            {
                "name": name,
                "head": head,
                "current": current,
                "visibility": VISIBILITY.get(visibility, "private"),
                "versions": versions,
            }
        )
    return pages, problems


# ---------------------------------------------------------------------------------------------
# Writing (only with --write)
# ---------------------------------------------------------------------------------------------


class Dest:
    """The few calls --write makes on the destination bucket."""

    def __init__(self, client, bucket: str):
        self.client, self.bucket = client, bucket

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        from ontic_pages.store import is_missing

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as err:
            if is_missing(err):
                return False
            raise

    def read_text(self, key: str) -> str:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read().decode()

    def put(self, key: str, body: bytes, ctype: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=ctype)


def dest_client(ctx, same_bucket: bool):
    """Two buckets: a client from the ontic-pages key (AWS_* or the config file). One bucket:
    that key when AWS_ACCESS_KEY_ID is set, else the ontic session's own client."""
    from ontic_pages.config import load_config
    from ontic_pages.store import make_client

    cfg = load_config()
    if same_bucket and not os.environ.get("AWS_ACCESS_KEY_ID"):
        client = getattr(ctx.store, "client", None)
        if client is not None:
            return client
    if not (cfg.access_key_id or os.environ.get("AWS_ACCESS_KEY_ID")):
        raise SystemExit(
            "no key for the destination bucket: set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY "
            "(a read-write key for it), or put them in ~/.config/ontic-pages/config.toml"
        )
    return make_client(cfg)


def write(
    ctx, mapping: dict, source_bucket: str, dest_bucket: str, prefix: str, client=None
) -> None:
    """Copy every version, then visibility, then current. Two buckets: each file is read with
    the ontic session's store and uploaded with the destination key. One bucket: server-side
    CopyObject. Never deletes; a version whose page.json exists is skipped."""
    names = [p["name"] for p in mapping["pages"]]
    bad = [n for n in names if not NAME_RE.match(n) or n in RESERVED_NAMES]
    if bad or len(set(names)) != len(names):
        raise SystemExit(f"bad or duplicate names in the mapping: {bad or names}")
    levels = [p.get("visibility") for p in mapping["pages"]]
    if any(level not in VISIBILITIES for level in levels):
        raise SystemExit(f"visibility must be one of {VISIBILITIES}, got {levels}")
    same = source_bucket == dest_bucket
    client = client or dest_client(ctx, same)
    dest = Dest(client, dest_bucket)
    print(
        f"{source_bucket} -> {dest_bucket}/{prefix} ({'server-side copy' if same else 'streamed'})"
    )
    for p in mapping["pages"]:
        name, ours = p["name"], {v["version"] for v in p["versions"]}
        cur_key = f"{prefix}{name}/current"
        if dest.exists(cur_key):
            existing = dest.read_text(cur_key).strip()
            if existing not in ours:
                print(f"skip {name}: it already serves {existing}, not a migrated version")
                continue
        for v in p["versions"]:
            base = f"{prefix}{name}/{v['version']}/"
            if dest.exists(base + "page.json"):
                print(f"  {name} {v['version']}: already there")
                continue
            size = 0
            for rel in v["files"]:
                src = f"jobs/{v['job']}/output/{DATA}{rel}"
                if same:
                    client.copy_object(
                        Bucket=dest_bucket,
                        Key=base + rel,
                        CopySource={"Bucket": source_bucket, "Key": src},
                        ContentType=content_type(rel),
                        MetadataDirective="REPLACE",
                    )
                else:
                    data = ctx.store.get(src)
                    dest.put(base + rel, data, content_type(rel))
                size += v["files"][rel]
            page = dict(v["page"], name=name, version=v["version"])
            dest.put(base + "page.json", json.dumps(page, indent=2).encode(), "application/json")
            print(f"  {name} {v['version']}: {len(v['files'])} files, {size / 1e6:.1f} MB")
        vis_key = f"{prefix}{name}/visibility"
        if not dest.exists(vis_key):  # before current: a private page is never briefly open
            dest.put(vis_key, p["visibility"].encode(), "text/plain")
        dest.put(cur_key, p["current"].encode(), "text/plain")
        print(f"{name} now serves {p['current']} ({p['visibility']})")


def main() -> None:
    from ontic_pages.config import load_config

    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mapping", required=True, type=Path, help="mapping JSON to write or read")
    ap.add_argument("--write", action="store_true", help="copy for real (reads --mapping)")
    ap.add_argument("--source-bucket", default="ontic-r3", help="old jobs (default ontic-r3)")
    ap.add_argument("--dest-bucket", default=cfg.bucket, help=f"pages (default {cfg.bucket})")
    ap.add_argument("--prefix", default=cfg.prefix, help="prefix in the destination (default none)")
    args = ap.parse_args()

    from ontic.cli_support import build_ctx

    ctx = build_ctx().ctx
    session_bucket = getattr(ctx.store, "bucket", None)
    if session_bucket and session_bucket != args.source_bucket:
        raise SystemExit(
            f"the ontic session reads {session_bucket}, not --source-bucket {args.source_bucket}"
        )
    if args.write:
        mapping = json.loads(args.mapping.read_text())
        write(ctx, mapping, args.source_bucket, args.dest_bucket, args.prefix)
        return

    keep = {}
    if args.mapping.exists():
        keep = {p["head"]: p["name"] for p in json.loads(args.mapping.read_text())["pages"]}
    pages, problems = plan(ctx, keep)
    total = files = 0
    for p in pages:
        size = sum(sum(v["files"].values()) for v in p["versions"])
        total += size
        files += sum(len(v["files"]) for v in p["versions"])
        print(
            f"{p['name']:24} {p['visibility']:8} {p['head']}  {len(p['versions'])} version(s)  "
            f"current {p['current']}  {size / 1e6:.1f} MB"
        )
    print(f"\n{len(pages)} pages, {files} files, {total / 1e6:.1f} MB")
    mapping = {
        "source_bucket": args.source_bucket,
        "dest_bucket": args.dest_bucket,
        "prefix": args.prefix,
        "pages": pages,
        "problems": problems,
    }
    args.mapping.write_text(json.dumps(mapping, indent=2))
    print(f"mapping written to {args.mapping} (dry run: nothing was written to any bucket)")
    if problems:
        print("\nproblems:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)


if __name__ == "__main__":
    main()
