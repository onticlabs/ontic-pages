"""crossorigin="anonymous" on a page's own media, added at publish (crossorigin.py)."""

from test_api import OWNER

from ontic_pages.cli import main
from ontic_pages.crossorigin import add_crossorigin
from ontic_pages.publish import publish

PAGE = """<p>x</p>
<img src="a.png">  <IMG
  src='b.png' alt=x>
<img src="https://ext.example/c.png"><img src="data:image/png;base64,AA">
<img crossorigin src="d.png">
<video controls><source src="v.mp4" type=video/mp4></video>
<video src="//cdn.example/x.mp4"></video><audio src="/s.mp3"></audio>
<img srcset="e.png 1x, e2.png 2x"><video><source src="https://ext.example/y.mp4"></video>
<script>var t = "<img src='z.png'>"; el.innerHTML = '<video src="q.mp4">';</script>
"""

WANT = """<p>x</p>
<img crossorigin="anonymous" src="a.png">  <IMG crossorigin="anonymous"
  src='b.png' alt=x>
<img src="https://ext.example/c.png"><img src="data:image/png;base64,AA">
<img crossorigin src="d.png">
<video crossorigin="anonymous" controls><source src="v.mp4" type=video/mp4></video>
<video src="//cdn.example/x.mp4"></video><audio crossorigin="anonymous" src="/s.mp3"></audio>
<img crossorigin="anonymous" srcset="e.png 1x, e2.png 2x"><video><source src="https://ext.example/y.mp4"></video>
<script>var t = "<img src='z.png'>"; el.innerHTML = '<video src="q.mp4">';</script>
"""


def test_only_own_media_outside_scripts():
    assert add_crossorigin(PAGE) == (WANT, 5)
    assert add_crossorigin(WANT) == (WANT, 0)  # once is enough


def test_line_endings_and_other_bytes_are_kept():
    page = '<p>\r\n<img src="a.png">\r\n</p>'
    assert add_crossorigin(page)[0] == '<p>\r\n<img crossorigin="anonymous" src="a.png">\r\n</p>'


def test_direct_publish_uploads_the_fixed_html(store, site, capsys):
    (site / "index.html").write_text('<img src="img/dot.png">')
    publish(store, site, "report")
    version = store.current("report")
    sent = store.get(store.key("report", version, "index.html"))["Body"].read()
    assert sent == b'<img crossorigin="anonymous" src="img/dot.png">'
    assert (site / "index.html").read_text() == '<img src="img/dot.png">'  # the source stays
    assert 'index.html: added crossorigin="anonymous" to 1 image/video/audio tag' in (
        capsys.readouterr().err
    )


def test_gateway_publish_uploads_the_fixed_html(local, gateway_env, store, site, capsys):
    (site / "docs" / "index.html").write_text('<video src="../clip.mp4"></video>')
    gateway_env(local(), OWNER)
    main(["publish", str(site), "--name", "report"])
    version = store.current("report")
    sent = store.get(store.key("report", version, "docs/index.html"))["Body"].read()
    assert sent == b'<video crossorigin="anonymous" src="../clip.mp4"></video>'
    assert store.meta("report", version)["files"] == 6
    assert "docs/index.html: added" in capsys.readouterr().err
