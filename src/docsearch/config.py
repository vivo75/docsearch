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

    @property
    def docs_dir(self) -> Path:
        return (self.path / self.docs_root).resolve()

    def in_scope(self, rel: str) -> bool:
        return not self.restrict or self.docs_root in (".", "") or rel.startswith(self.docs_root.rstrip("/") + "/")

    def rel(self, p: Path) -> str:
        """Repo-relative POSIX path."""
        return p.resolve().relative_to(self.path.resolve()).as_posix()


@dataclass(frozen=True)
class Config:
    root: Path
    repos: tuple[Repo, ...]

    def repo(self, name: str) -> Repo:
        return next(r for r in self.repos if r.name == name)


def load_config(path: str | Path) -> Config:
    data = tomllib.loads(Path(path).read_text())
    root = Path(data["root"])
    repos = tuple(
        Repo(r["name"], root / r["name"], r.get("docs_root", "."), r.get("weight", 1.0), r.get("url_base"), r.get("restrict", False))
        for r in data["repo"]
    )
    return Config(root, repos)
