import pytest

from ontic_pages.config import DEFAULT_PREFIX, DEFAULT_URL, load_config


def test_defaults_without_file_or_env(tmp_path):
    cfg = load_config(tmp_path / "none.toml", env={})
    assert cfg.bucket is None
    assert cfg.prefix == DEFAULT_PREFIX
    assert cfg.url == DEFAULT_URL
    assert cfg.page_url("report") == "https://pages.onticlabs.io/report/"


def test_file_then_env_override(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'bucket = "from-file"\nendpoint = "https://s3.example.com"\nregion = "eu"\n'
        'prefix = "team-pages"\naccess_key_id = "id-from-file"\n'
    )
    cfg = load_config(path, env={})
    assert (cfg.bucket, cfg.endpoint, cfg.region) == ("from-file", "https://s3.example.com", "eu")
    assert cfg.prefix == "team-pages/"
    assert cfg.access_key_id == "id-from-file"

    env = {
        "ONTIC_PAGES_BUCKET": "from-env",
        "AWS_ACCESS_KEY_ID": "id-from-env",
        "ONTIC_PAGES_URL": "http://localhost:8790/",
    }
    cfg = load_config(path, env=env)
    assert cfg.bucket == "from-env"
    assert cfg.access_key_id == "id-from-env"
    assert cfg.endpoint == "https://s3.example.com"
    assert cfg.page_url("a") == "http://localhost:8790/a/"


def test_unknown_key_is_refused(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('buckit = "typo"\n')
    with pytest.raises(SystemExit, match="unknown keys"):
        load_config(path, env={})


def test_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "ontic-pages").mkdir()
    (tmp_path / "ontic-pages" / "config.toml").write_text('bucket = "xdg"\n')
    monkeypatch.delenv("ONTIC_PAGES_BUCKET", raising=False)
    assert load_config().bucket == "xdg"
