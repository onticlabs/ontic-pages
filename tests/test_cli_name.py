from ontic_pages.cli import build_parser


def test_help_names_the_command_it_was_run_as(monkeypatch):
    monkeypatch.setattr("sys.argv", ["/home/u/.local/bin/ontic", "pages"])
    assert build_parser().prog == "ontic pages"
    monkeypatch.setattr("sys.argv", ["/home/u/.local/bin/ontic-pages"])
    assert build_parser().prog == "ontic-pages"


def test_help_name_from_the_ontic_cli(monkeypatch):
    monkeypatch.setattr("sys.argv", ["/home/u/.cache/uv/archive-v0/x/bin/ontic-pages"])
    monkeypatch.setenv("ONTIC_PAGES_PROG", "ontic pages")
    assert build_parser().prog == "ontic pages"


def test_help_text_names_the_command(monkeypatch):
    monkeypatch.setenv("ONTIC_PAGES_PROG", "ontic pages")
    help_text = build_parser().format_help()
    assert "ontic pages login" in help_text and "ontic-pages" not in help_text
