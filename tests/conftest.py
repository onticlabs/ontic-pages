import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fake_s3 import FakeS3  # noqa: E402

from ontic_pages.store import Store  # noqa: E402


@pytest.fixture
def s3():
    return FakeS3()


@pytest.fixture
def store(s3):
    return Store(s3, "test-bucket", "pages/")


@pytest.fixture
def site(tmp_path):
    """A small page folder: index, a stylesheet, a script, an image, a sub folder."""
    root = tmp_path / "site"
    (root / "img").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "index.html").write_text("<h1>version one</h1>")
    (root / "style.css").write_text("h1 { color: red }")
    (root / "app.js").write_text("console.log(1)")
    (root / "data.json").write_text('{"a": 1}')
    (root / "img" / "dot.png").write_bytes(b"\x89PNG\r\n\x1a\n0123456789")
    (root / "docs" / "index.html").write_text("<p>docs</p>")
    (root / ".DS_Store").write_bytes(b"junk")
    return root


@pytest.fixture
def cli_env(s3, tmp_path, monkeypatch):
    """Run the real command line against the fake store, with no config file."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("ONTIC_PAGES_BUCKET", "test-bucket")
    monkeypatch.setenv("ONTIC_PAGES_URL", "https://pages.example.org")
    monkeypatch.setattr("ontic_pages.cli.make_client", lambda cfg: s3)
    return s3
