"""ontic-pages: publish HTML to the team's bucket and serve it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import gateway
from .config import load_config
from .info import history, info_text
from .publish import parse_input, publish
from .store import VERSION_RE, Store, check_name, make_client


def parse_meta(items: list[str]) -> dict[str, str]:
    meta = {}
    for item in items:
        key, eq, value = item.partition("=")
        if not eq or not key:
            raise SystemExit(f"--meta wants key=value, got {item!r}")
        meta[key] = value
    return meta


def open_store(args) -> tuple[Store, object]:
    cfg = load_config()
    bucket = getattr(args, "bucket", None) or cfg.bucket
    return Store(make_client(cfg), bucket, cfg.prefix), cfg


def cmd_publish(args) -> None:
    store, cfg = open_store(args)
    source = Path(args.source)
    if source.is_dir() and not (source / "index.html").exists():
        print(f"warning: {source} has no index.html; the page URL will answer 404", file=sys.stderr)
    inputs = [parse_input(x) for x in args.inputs]
    page = publish(store, source, args.name, args.description, parse_meta(args.meta), inputs)
    print(f"published {page['name']} version {page['version']} ({page['files']} files)")
    print(cfg.page_url(args.name))


def cmd_list(args) -> None:
    store, _ = open_store(args)
    if args.name:
        check_name(args.name)
        current = store.current(args.name)
        versions = store.versions(args.name)
        if not versions:
            raise SystemExit(f"no page named {args.name}")
        for version in reversed(versions):
            meta = store.meta(args.name, version)
            mark = "*" if version == current else " "
            by, desc = meta.get("published_by", ""), meta.get("description", "")
            print(f"{mark} {version}  {by}  {desc}")
        return
    for name in store.names():
        current = store.current(name)
        if current:
            desc = store.meta(name, current).get("description", "")
            print(f"{name:32} {current}  {desc}")


def cmd_set_current(args) -> None:
    store, cfg = open_store(args)
    check_name(args.name)
    if not VERSION_RE.match(args.version) or args.version not in store.versions(args.name):
        raise SystemExit(f"{args.name} has no version {args.version} (see: list --name)")
    store.set_current(args.name, args.version)
    print(f"{args.name} now serves {args.version}")
    print(cfg.page_url(args.name))


def cmd_info(args) -> None:
    store, _ = open_store(args)
    current, metas = history(store, check_name(args.name))
    if not metas:
        raise SystemExit(f"no page named {args.name}")
    print(info_text(args.name, current, metas))


def cmd_url(args) -> None:
    print(load_config().page_url(check_name(args.name)))


def cmd_gateway(args) -> None:
    store, _ = open_store(args)
    gateway.serve(store, args.host, args.port, args.cache_seconds)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ontic-pages", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("publish", help="upload a folder or .html file as a new version")
    s.add_argument("source", help="a folder (with index.html) or a single .html file")
    s.add_argument("--name", required=True, help="page name, part of the URL")
    s.add_argument("--description", default="", help="one line shown in listings")
    s.add_argument(
        "--meta",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="any other metadata, repeatable",
    )
    s.add_argument(
        "--from",
        dest="inputs",
        action="append",
        default=[],
        metavar="KIND:REF[@HASH]",
        help="what the page was made from, repeatable; KIND is model, dataset, checkpoint, "
        "job or run (for example model:da3-backbone@sha256:9f1c...)",
    )
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser("list", help="list pages, or the versions of one page")
    s.add_argument("--name", help="show the versions of this page")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("set-current", help="serve an earlier (or later) version of a page")
    s.add_argument("name")
    s.add_argument("version", help="a version id from `list --name`")
    s.set_defaults(func=cmd_set_current)

    s = sub.add_parser("info", help="show a page's metadata and versions")
    s.add_argument("name")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("url", help="print the URL of a page")
    s.add_argument("name")
    s.set_defaults(func=cmd_url)

    s = sub.add_parser("gateway", help="serve the bucket over HTTP (runs on the server)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8790)
    s.add_argument("--bucket", help="overrides ONTIC_PAGES_BUCKET")
    s.add_argument(
        "--cache-seconds",
        type=float,
        default=5.0,
        help="how long a page's current version is remembered (default 5)",
    )
    s.set_defaults(func=cmd_gateway)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except ValueError as err:
        raise SystemExit(str(err)) from None
