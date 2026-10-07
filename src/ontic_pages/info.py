"""What is known about a page, from its page.json files: for `ontic-pages info` and the
gateway's /<name>/_info page."""

from __future__ import annotations

import html
import re
from urllib.parse import quote

from .store import Store

GITHUB_RE = re.compile(r"^(?:https://|ssh://git@|git@)github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$")


def history(store: Store, name: str) -> tuple[str | None, list[dict]]:
    """The current version and every version's page.json, newest first."""
    versions = store.versions(name)
    metas = [store.meta(name, v) or {"name": name, "version": v} for v in reversed(versions)]
    return store.current(name), metas


def github_url(remote: str | None) -> str | None:
    m = GITHUB_RE.match(remote or "")
    return f"https://github.com/{m.group(1)}" if m else None


def input_label(item: dict) -> str:
    label = f"{item.get('kind', '?')}: {item.get('ref', '')}"
    return label + (f" @ {item['hash']}" if item.get("hash") else "")


def git_label(git: dict | None) -> str:
    if not git:
        return "none recorded"
    dirty = " (uncommitted changes)" if git.get("dirty") else ""
    return f"{git.get('remote') or 'no remote'} {git.get('branch') or ''} " + (
        f"{(git.get('commit') or '')[:8]}{dirty}"
    )


def shown(current: str | None, metas: list[dict]) -> dict:
    """The page.json of the current version (else the newest one)."""
    return next((m for m in metas if m.get("version") == current), metas[0] if metas else {})


def info_text(name: str, current: str | None, metas: list[dict]) -> str:
    page = shown(current, metas)
    lines = [
        f"page         {name}",
        f"current      {current}",
        f"published    {page.get('published_at', '')} by {page.get('published_by', '')}",
        f"description  {page.get('description', '')}",
        f"git          {git_label(page.get('git'))}",
    ]
    lines += [f"input        {input_label(i)}" for i in page.get("inputs", [])]
    lines += [f"meta         {k} = {v}" for k, v in page.get("meta", {}).items()]
    lines.append("versions")
    for m in metas:
        mark = "*" if m.get("version") == current else " "
        lines.append(
            f"  {mark} {m.get('version')}  {m.get('published_by', '')}  {m.get('description', '')}"
        )
    return "\n".join(lines)


def info_html(name: str, current: str | None, metas: list[dict]) -> str:
    e = html.escape
    page = shown(current, metas)
    inputs = "".join(f"<li>{e(input_label(i))}</li>" for i in page.get("inputs", []))
    meta = "".join(
        f"<tr><th>{e(str(k))}</th><td>{e(str(v))}</td></tr>"
        for k, v in page.get("meta", {}).items()
    )
    git = page.get("git") or {}
    repo = github_url(git.get("remote"))
    commit = git.get("commit") or ""
    if git:
        remote = f'<a href="{e(repo)}">{e(repo)}</a>' if repo else e(git.get("remote") or "none")
        short = e(commit[:8])
        commit_html = f'<a href="{e(repo)}/commit/{e(commit)}">{short}</a>' if repo else short
        dirty = " (uncommitted changes)" if git.get("dirty") else ""
        git_html = f"{remote}, branch {e(git.get('branch') or '')}, commit {commit_html}{dirty}"
    else:
        git_html = "none recorded"
    published = f"{e(page.get('published_at', ''))} by {e(page.get('published_by', ''))}"
    versions = "".join(
        f"<li>{'<b>' if m.get('version') == current else ''}{e(m.get('version', ''))} "
        f"{e(m.get('published_by', ''))} {e(m.get('description', ''))}"
        f"{' (current)</b>' if m.get('version') == current else ''}</li>"
        for m in metas
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{e(name)}: page info</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem; padding: 0 1rem; }}
th, td {{ text-align: left; padding: .2rem .6rem .2rem 0; vertical-align: top; }}
</style></head><body>
<p><a href="/">All pages</a></p>
<h1><a href="/{quote(name)}/">{e(name)}</a></h1>
<p>{e(page.get("description", ""))}</p>
<table>
<tr><th>Published</th><td>{published}</td></tr>
<tr><th>Version</th><td>{e(current or "")}</td></tr>
<tr><th>Git</th><td>{git_html}</td></tr>
</table>
<h2>Inputs</h2>
{f"<ul>{inputs}</ul>" if inputs else "<p>None recorded.</p>"}
<h2>Metadata</h2>
{f"<table>{meta}</table>" if meta else "<p>None recorded.</p>"}
<h2>Versions</h2>
<ul>{versions}</ul>
</body></html>
"""
