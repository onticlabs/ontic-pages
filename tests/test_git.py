import subprocess

from ontic_pages.publish import git_provenance, publish, strip_userinfo


def run(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_outside_git(tmp_path):
    assert git_provenance(tmp_path) is None


def test_git_repo(tmp_path, store, site):
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "init", "-q", "-b", "trunk")
    (repo / "a.txt").write_text("a")
    run(repo, "add", "a.txt")
    run(repo, "commit", "-q", "-m", "first")
    run(repo, "remote", "add", "origin", "https://user:secret-token@github.com/onticlabs/x.git")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    prov = git_provenance(repo)
    assert prov == {
        "remote": "https://github.com/onticlabs/x.git",
        "branch": "trunk",
        "commit": sha,
        "dirty": False,
    }

    (repo / "a.txt").write_text("changed")
    assert git_provenance(repo)["dirty"] is True

    page = publish(store, site, "report", cwd=repo)
    assert page["git"]["commit"] == sha and page["git"]["dirty"] is True


def test_strip_userinfo():
    assert strip_userinfo("git@github.com:onticlabs/x.git") == "git@github.com:onticlabs/x.git"
    assert strip_userinfo("https://tok@github.com/a/b") == "https://github.com/a/b"
