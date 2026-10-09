"""ontic-pages: publish HTML pages for the team and serve them.

The commands talk to the gateway (ONTIC_PAGES_URL) signed in with `ontic-pages login`; with
--direct (or ONTIC_PAGES_DIRECT=1) they use your own bucket key instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import gateway, remote, skills
from .auth import DEFAULT_AUTH_URL
from .cache import MB
from .config import Config, load_config, token_path
from .info import history, info_text
from .publish import publish
from .store import VERSION_RE, VISIBILITIES, Store, check_name, make_client

LEVELS = "private (only you), ontic (signed-in team, the default), public (anyone with the link)"


def parse_meta(items: list[str]) -> dict[str, str]:
    meta = {}
    for item in items:
        key, eq, value = item.partition("=")
        if not eq or not key:
            raise SystemExit(f"--meta wants key=value, got {item!r}")
        meta[key] = value
    return meta


def open_store(args) -> tuple[Store, Config]:
    cfg = load_config()
    bucket = getattr(args, "bucket", None) or cfg.bucket
    return Store(make_client(cfg), bucket, cfg.prefix), cfg


def direct(args) -> bool:
    return getattr(args, "direct", False) or load_config().is_direct


def open_api() -> tuple[remote.Api, Config]:
    cfg = load_config()
    return remote.Api(cfg.url, remote.load_token()), cfg


def owner_note(owner: str) -> None:
    print(f"private: only {owner or 'its publisher'} can open it, signed in with that address")


def url_for(store: Store, cfg: Config, name: str) -> str:
    return cfg.page_url(name)


def private_note(store: Store, name: str) -> None:
    current = store.current(name)
    owner_note(store.meta(name, current).get("published_by", "") if current else "")


def cmd_publish(args) -> None:
    source = Path(args.source)
    if source.is_dir() and not (source / "index.html").exists():
        print(f"warning: {source} has no index.html; the page URL will answer 404", file=sys.stderr)
    if not direct(args):
        api, cfg = open_api()
        check_name(args.name)
        done = remote.publish(
            api, source, args.name, args.description, parse_meta(args.meta), args.visibility
        )
        page = done["page"]
        print(f"published {page['name']} version {page['version']} ({page['files']} files)")
        if done.get("visibility") == "private":
            owner_note(page["published_by"])
        print(cfg.page_url(args.name))
        return
    store, cfg = open_store(args)
    page = publish(
        store, source, args.name, args.description, parse_meta(args.meta),
        visibility=args.visibility, published_by=cfg.email,
    )  # fmt: skip
    print(f"published {page['name']} version {page['version']} ({page['files']} files)")
    if store.visibility(args.name) == "private":
        private_note(store, args.name)
    print(url_for(store, cfg, args.name))


def cmd_share(args) -> None:
    check_name(args.name)
    if not direct(args):
        api, cfg = open_api()
        page = api.post(remote.page_path(args.name, "visibility"), {"visibility": args.visibility})
        print(f"{args.name} is now {page['visibility']}")
        if page["visibility"] == "private":
            owner_note(page.get("published_by", ""))
        print(cfg.page_url(args.name))
        return
    store, cfg = open_store(args)
    if not store.current(args.name):
        raise SystemExit(f"no page named {args.name}")
    store.set_visibility(args.name, args.visibility)
    print(f"{args.name} is now {args.visibility}")
    if args.visibility == "private":
        private_note(store, args.name)
    print(url_for(store, cfg, args.name))


def cmd_list(args) -> None:
    if not direct(args):
        return list_remote(args)
    store, _ = open_store(args)
    if args.name:
        check_name(args.name)
        current = store.current(args.name)
        versions = store.versions(args.name)
        if not versions:
            raise SystemExit(f"no page named {args.name}")
        print(f"visibility: {store.visibility(args.name)}")
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
            print(f"{name:32} {store.visibility(name):8} {current}  {desc}")


def list_remote(args) -> None:
    api, _ = open_api()
    if args.name:
        check_name(args.name)
        page = api.get(remote.page_path(args.name))
        print(f"visibility: {page['visibility']}")
        for v in page["versions"]:
            mark = "*" if v["version"] == page["current"] else " "
            print(f"{mark} {v['version']}  {v.get('published_by', '')}  {v['description']}")
        return
    for p in api.get("/_api/pages")["pages"]:
        print(f"{p['name']:32} {p['visibility']:8} {p['current']}  {p['description']}")


def cmd_set_current(args) -> None:
    check_name(args.name)
    if not direct(args):
        api, cfg = open_api()
        if not VERSION_RE.match(args.version):
            raise SystemExit(f"{args.name} has no version {args.version} (see: list --name)")
        api.post(remote.page_path(args.name, "current"), {"version": args.version})
        print(f"{args.name} now serves {args.version}")
        print(cfg.page_url(args.name))
        return
    store, cfg = open_store(args)
    if not VERSION_RE.match(args.version) or args.version not in store.versions(args.name):
        raise SystemExit(f"{args.name} has no version {args.version} (see: list --name)")
    store.set_current(args.name, args.version)
    print(f"{args.name} now serves {args.version}")
    print(url_for(store, cfg, args.name))


def cmd_info(args) -> None:
    check_name(args.name)
    if not direct(args):
        api, _ = open_api()
        page = api.get(remote.page_path(args.name, "info"))
        print(info_text(args.name, page["current"], page["versions"], page["visibility"]))
        return
    store, _ = open_store(args)
    current, metas = history(store, args.name)
    if not metas:
        raise SystemExit(f"no page named {args.name}")
    print(info_text(args.name, current, metas, store.visibility(args.name)))


def cmd_url(args) -> None:
    print(load_config().page_url(check_name(args.name)))


def cmd_login(args) -> None:
    api, _ = open_api()
    email = remote.login(api)
    print(f"signed in as {email} (for 30 days; the token is in {token_path()})")


def cmd_logout(args) -> None:
    path = token_path()
    if path.exists():
        path.unlink()
        print(f"signed out (removed {path})")
    else:
        print("not signed in")


def cmd_whoami(args) -> None:
    api, cfg = open_api()
    print(api.get("/_api/me")["email"])


def cmd_skill(args) -> None:
    if args.print:
        sys.stdout.write(skills.bundled())
        return
    rows = skills.install() if args.install else skills.status()
    for agent, target, state in rows:
        print(f"{agent}: {target}\n  {state}")
    if not args.install:
        print(
            "To get ours back over your own copy, delete that file (it comes back on the next "
            "run) or run ontic-pages skill --install."
        )


def cmd_gateway(args) -> None:
    store, cfg = open_store(args)
    if args.local_as and args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("--local-as is for a gateway on this machine only (--host 127.0.0.1)")
    # Run locally, the apex is localhost and each page is <name>.localhost (browsers send
    # *.localhost to this machine), over plain http.
    url = args.url or (f"http://localhost:{args.port}" if args.local_as else cfg.url)
    suffix = args.content_suffix or ("" if args.local_as and not args.url else cfg.content_suffix)
    gateway.serve(
        store, args.host, args.port,
        site=gateway.Site(url.rstrip("/"), suffix, args.email_domain),
        ttl=args.cache_seconds,
        local_email=args.local_as or "",
        auth_url=args.auth_url,
        cache_bytes=int(args.cache_mb * MB),
        file_bytes=int(args.cache_file_mb * MB),
        token_secret=cfg.token_secret,
    )  # fmt: skip


def build_parser() -> argparse.ArgumentParser:
    # Run as `ontic pages ...` through the ontic CLI, or as `ontic-pages ...` on its own.
    prog = "ontic pages" if Path(sys.argv[0]).name == "ontic" else "ontic-pages"
    p = argparse.ArgumentParser(prog=prog, description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    key = argparse.ArgumentParser(add_help=False)
    key.add_argument(
        "--direct",
        action="store_true",
        help="use your own bucket key, not the gateway (admins; also ONTIC_PAGES_DIRECT=1)",
    )

    s = sub.add_parser("login", help="sign in the command line with Google, in the browser")
    s.set_defaults(func=cmd_login)
    s = sub.add_parser("logout", help="forget the sign-in on this machine")
    s.set_defaults(func=cmd_logout)
    s = sub.add_parser("whoami", help="print who you are signed in as")
    s.set_defaults(func=cmd_whoami)

    s = sub.add_parser(
        "publish", parents=[key], help="upload a folder or .html file as a new version"
    )
    s.add_argument("source", help="a folder (with index.html) or a single .html file")
    s.add_argument("--name", required=True, help="page name, part of the URL")
    s.add_argument("--description", default="", help="one line shown in listings")
    s.add_argument(
        "--meta",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="any metadata, repeatable (for example model=<hash>)",
    )
    s.add_argument(
        "--visibility",
        choices=VISIBILITIES,
        help=f"who can open it: {LEVELS}; without it a new page is ontic and an existing "
        "page keeps its level",
    )
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser("share", parents=[key], help="change who can open a page")
    s.add_argument("name")
    s.add_argument("visibility", choices=VISIBILITIES, help=LEVELS)
    s.set_defaults(func=cmd_share)

    s = sub.add_parser(
        "list", parents=[key], help="list pages with their visibility, or the versions of one"
    )
    s.add_argument("--name", help="show the versions of this page")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser(
        "set-current", parents=[key], help="serve an earlier (or later) version of a page"
    )
    s.add_argument("name")
    s.add_argument("version", help="a version id from `list --name`")
    s.set_defaults(func=cmd_set_current)

    s = sub.add_parser(
        "info", parents=[key], help="show a page's metadata, visibility and versions"
    )
    s.add_argument("name")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("url", help="print a page's URL")
    s.add_argument("name")
    s.set_defaults(func=cmd_url)

    s = sub.add_parser(
        "skill", help="show where the agent skill is installed for Claude Code and Codex"
    )
    which = s.add_mutually_exclusive_group()
    which.add_argument(
        "--install",
        action="store_true",
        help="write ours, also over your own copy (never over a symlink)",
    )
    which.add_argument("--print", action="store_true", help="print the bundled skill text")
    s.set_defaults(func=cmd_skill)

    s = sub.add_parser("gateway", help="serve the bucket over HTTP (runs on the server)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8790)
    s.add_argument("--bucket", help="overrides ONTIC_PAGES_BUCKET")
    s.add_argument(
        "--cache-seconds",
        type=float,
        default=5.0,
        help="how long a page's current version and visibility are remembered (default 5)",
    )
    s.add_argument(
        "--url",
        help="the apex, scheme and host (default ONTIC_PAGES_URL, or http://localhost:<port> "
        "with --local-as)",
    )
    s.add_argument(
        "--content-suffix",
        help="pages are served from <name>.<suffix> (default ONTIC_PAGES_CONTENT_SUFFIX, "
        "else the apex host)",
    )
    s.add_argument(
        "--email-domain",
        default="onticlabs.io",
        help="ontic pages need a signed-in email at this domain (default onticlabs.io)",
    )
    s.add_argument(
        "--auth-url",
        default=DEFAULT_AUTH_URL,
        help=f"oauth2-proxy's auth endpoint, asked with the request's cookie "
        f"(default {DEFAULT_AUTH_URL})",
    )
    s.add_argument(
        "--cache-mb", type=float, default=256, help="memory for page files (default 256)"
    )
    s.add_argument(
        "--cache-file-mb",
        type=float,
        default=4,
        help="files larger than this are streamed, not kept in memory (default 4)",
    )
    s.add_argument(
        "--local-as",
        metavar="EMAIL",
        help="for looking at pages on this machine: act as EMAIL instead of asking "
        "oauth2-proxy, at http://localhost:<port>/ (loopback only)",
    )
    s.set_defaults(func=cmd_gateway)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command not in ("gateway", "skill"):
        # Reinstalling the tool runs no code, so the agent skill is refreshed on every run.
        skills.sync_skill()
    try:
        args.func(args)
    except ValueError as err:
        raise SystemExit(str(err)) from None
