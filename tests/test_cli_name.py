from ontic_pages.cli import build_parser


def test_help_names_the_command_it_was_run_as(monkeypatch):
    monkeypatch.setattr("sys.argv", ["/home/u/.local/bin/ontic", "pages"])
    assert build_parser().prog == "ontic pages"
    monkeypatch.setattr("sys.argv", ["/home/u/.local/bin/ontic-pages"])
    assert build_parser().prog == "ontic-pages"
