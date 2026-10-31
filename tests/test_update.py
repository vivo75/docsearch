import hashlib
import re
import subprocess
from array import array
from pathlib import Path

import pytest

from docsearch import store
from docsearch.build import build
from docsearch.update import make_plan, update, verify


class FakeEmb:
    truncated = 0

    def __init__(self, fail=False):
        self.texts, self.fail = [], fail

    def embed(self, texts, prefix="", est=None):
        if self.fail:
            raise RuntimeError("embedder down")
        self.texts += texts
        out = []
        for t in texts:
            v = [0.0] * store.DIMS
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % store.DIMS] += 1.0
            n = sum(x * x for x in v) ** 0.5 or 1.0
            out.append(array("f", [x / n for x in v]).tobytes())
        return out


def sh(cwd, *a):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


def commit(repo: Path, msg: str):
    sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", msg)


def page(title, body):
    return f"---\ntitle: {title}\nms.service: svc\nms.topic: how-to\n---\n# {title}\n\n## Steps\n\n{body}\n"


@pytest.fixture()
def env(tmp_path):
    repo = tmp_path / "r"
    (repo / "articles").mkdir(parents=True); (repo / "includes").mkdir()
    sh(repo, "git", "init", "-q"); sh(repo, "git", "config", "user.email", "a@b"); sh(repo, "git", "config", "user.name", "n")
    (repo / "includes/inc.md").write_text("Shared note about quotas.")
    (repo / "articles/a.md").write_text(page("Alpha", "Alpha body text. [!INCLUDE [n](../includes/inc.md)]"))
    (repo / "articles/b.md").write_text(page("Bravo", "Bravo body text about queues."))
    (repo / "articles/c.md").write_text(page("Charlie", "Charlie body text about networking."))
    (repo / "articles/d.md").write_text(page("Delta", "Delta body text that will vanish."))
    commit(repo, "init")
    cfg = tmp_path / "repos.toml"
    cfg.write_text(f'root = "{tmp_path}"\n[[repo]]\nname = "r"\ndocs_root = "articles"\nurl_base = "https://learn.microsoft.com/azure"\n')
    out = tmp_path / "data"
    build(str(cfg), out, embedder=FakeEmb(), workers=1)
    return repo, str(cfg), out


def docs(out):
    db = store.connect(out / "current.db", readonly=True)
    return {p for (p,) in db.execute("SELECT path FROM docs")}


def test_noop_then_incremental_changes(env):
    repo, cfg, out = env
    assert update(cfg, out, workers=1, embedder=FakeEmb())["status"] == "up-to-date"
    before = (out / "current.db").resolve().name

    (repo / "includes/inc.md").write_text("Shared note about quotas and limits.")     # dependency of a.md only
    (repo / "articles/b.md").write_text(page("Bravo", "Bravo body text about queues and topics."))
    (repo / "articles/e.md").write_text(page("Echo", "Echo is a brand new page."))
    (repo / "articles/d.md").unlink()
    commit(repo, "change")

    db = store.connect(out / "current.db", readonly=True)
    plan = make_plan(__import__("docsearch.config", fromlist=["load_config"]).load_config(cfg), db)
    rp = plan.repos["r"]
    assert rp.pages == {"articles/a.md", "articles/b.md", "articles/e.md"} and rp.removed == {"articles/d.md"} and not rp.full
    assert update(cfg, out, dry_run=True)["status"] == "dry-run" and (out / "current.db").resolve().name == before

    emb = FakeEmb()
    st = update(cfg, out, workers=1, embedder=emb)
    assert st["status"] == "published" and (out / "current.db").resolve().name != before
    assert docs(out) == {"articles/a.md", "articles/b.md", "articles/c.md", "articles/e.md"}
    joined = " ".join(emb.texts)
    assert "limits" in joined and "topics" in joined and "brand new" in joined       # changed content embedded
    assert "Charlie" not in joined and "networking" not in joined                    # untouched page not re-embedded
    new = store.connect(out / "current.db", readonly=True)
    assert store.health(new) == [] and store.get_meta(new)["head:r"] == subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert "limits" in new.execute("SELECT text FROM chunks c JOIN docs d USING(doc_id) WHERE d.path='articles/a.md'").fetchone()[0]
    assert update(cfg, out, workers=1, embedder=FakeEmb())["status"] == "up-to-date"
    assert verify(cfg, out / "current.db", 50)["mismatches"] == 0


def test_failed_update_leaves_live_index_untouched(env):
    repo, cfg, out = env
    live = (out / "current.db").resolve()
    (repo / "articles/b.md").write_text(page("Bravo", "Totally different text now."))
    commit(repo, "edit")
    with pytest.raises(RuntimeError):
        update(cfg, out, workers=1, embedder=FakeEmb(fail=True))
    assert (out / "current.db").resolve() == live
    assert not list(out.glob("*.partial*"))
    assert "Totally different" not in store.connect(live, readonly=True).execute(
        "SELECT group_concat(text) FROM chunks").fetchone()[0]


def test_unknown_old_head_falls_back_to_full_reprocess_reusing_vectors(env):
    repo, cfg, out = env
    # simulate a shallow clone that lost the recorded commit
    live = (out / "current.db").resolve()
    db = store.connect(live)
    store.set_meta(db, **{"head:r": "0" * 40}); db.commit(); db.close()
    emb = FakeEmb()
    st = update(cfg, out, workers=1, embedder=emb)
    assert st["status"] == "published" and st["reprocess"] == 4
    assert emb.texts == []                         # identical content -> every vector reused by hash
    assert docs(out) == {"articles/a.md", "articles/b.md", "articles/c.md", "articles/d.md"}
