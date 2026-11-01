from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

EXCLUDE_DIRS = frozenset({"includes", "_themes", "obj", "node_modules", ".git"})


@dataclass(frozen=True)
class Repo:
    name: str
    path: Path
    docs_root: str
    weight: float = 1.0
    url_base: str | None = None  # public site base, None = not published to Learn
    restrict: bool = False       # index only files under docs_root (repos holding several doc versions side by side)
    fmt: str = "md"              # "md" | "azcli-yaml" (Azure CLI reference YAML, converted to Markdown by azcli.py)

    @property
    def docs_dir(self) -> Path:
        return (self.path / self.docs_root).resolve()

    def in_scope(self, rel: str) -> bool:
        return not self.restrict or self.docs_root in (".", "") or rel.startswith(self.docs_root.rstrip("/") + "/")

    def rel(self, p: Path) -> str:
        """Repo-relative POSIX path."""
        return p.resolve().relative_to(self.path.resolve()).as_posix()

    def rel_dir(self, root: Path) -> str:
        """The checkout directory relative to the corpus root (differs from `name` when repos.toml sets `path`)."""
        return self.path.resolve().relative_to(root.resolve()).as_posix()


@dataclass(frozen=True)
class Config:
    root: Path
    repos: tuple[Repo, ...]

    def repo(self, name: str) -> Repo:
        return next(r for r in self.repos if r.name == name)

    def checkouts(self) -> list[Repo]:
        """One entry per distinct checkout directory, in config order (several entries may share a checkout)."""
        seen: dict[Path, Repo] = {}
        for r in self.repos:
            seen.setdefault(r.path.resolve(), r)
        return list(seen.values())

    def sharing(self, repo: Repo) -> list[Repo]:
        """All entries whose checkout is the same directory as `repo`'s (including `repo`)."""
        return [r for r in self.repos if r.path.resolve() == repo.path.resolve()]

    def source_for(self, corpus_rel: str) -> str | None:
        """Corpus-relative path (`<checkout dir>/<file>`) -> source id `<entry name>/<repo-relative path>`, choosing the
        entry whose scope covers the file; None when no configured checkout contains it."""
        root = self.root.resolve()
        for r in self.repos:
            d = r.rel_dir(root)
            if corpus_rel.startswith(d + "/"):
                rel = corpus_rel[len(d) + 1:]
                owner = next((x for x in self.sharing(r) if x.in_scope(rel)), r)
                return f"{owner.name}/{rel}"
        return None


def load_config(path: str | Path) -> Config:
    data = tomllib.loads(Path(path).read_text())
    root = (Path(path).parent / data["root"]).resolve()   # relative roots resolve against the config file
    repos = tuple(
        Repo(r["name"], root / r.get("path", r["name"]), r.get("docs_root", "."), r.get("weight", 1.0), r.get("url_base"),
             r.get("restrict", False), r.get("format", "md"))       # `path`: checkout dir when several entries share one repo
        for r in data["repo"]
    )
    return Config(root, repos)
