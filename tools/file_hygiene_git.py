"""Read-only, bounded Git access shared by file hygiene and CI routing."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")


def git(repo: Path, *args: str, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], input=input_data,
        capture_output=True, timeout=30, check=False,
    )
    if result.returncode:
        raise ValueError(f"Git read failed: {' '.join(args[:2])}; exit={result.returncode}")
    return result.stdout


def blob(repo: Path, revision: str, path: str) -> bytes:
    return git(repo, "show", revision + ":" + path)


@dataclass(frozen=True)
class Change:
    status: str
    path: str
    previous: str | None = None


def changes(repo: Path, base: str, head: str) -> list[Change]:
    fields = git(repo, "diff", "--name-status", "-z", "-M", "-C", base, head, "--").split(b"\0")
    fields = [part.decode("utf-8") for part in fields if part]
    out: list[Change] = []
    i = 0
    while i < len(fields):
        status = fields[i]
        width = 3 if status.startswith(("R", "C")) else 2
        if i + width > len(fields):
            raise ValueError("Truncated Git diff record")
        previous = fields[i + 1] if width == 3 else None
        out.append(Change(status, fields[i + width - 1], previous))
        i += width
    return out


def comparison_base(repo: Path, base: str, head: str, mode: str = "merge-base") -> str:
    for value in (base, head):
        if not SHA.fullmatch(value):
            raise ValueError("base and head must be full 40-hex commit SHAs")
        git(repo, "cat-file", "-e", value + "^{commit}")
    if mode == "direct":
        return base
    if mode != "merge-base":
        raise ValueError("Unknown comparison mode")
    bases = git(repo, "merge-base", "--all", base, head).decode("ascii").splitlines()
    if len(bases) != 1:
        raise ValueError("A single common ancestor is required; synchronize this branch")
    return bases[0]


class GitTree:
    """Reads only tracked blobs, never follows checkout symlinks or mounts."""
    def __init__(self, repo: Path, revision: str):
        self.repo, self.revision = repo, revision
        self.files: dict[str, tuple[str, str]] = {}
        self.directories: set[str] = set()
        for entry in git(repo, "ls-tree", "-r", "-z", revision).split(b"\0"):
            if not entry:
                continue
            info, name = entry.split(b"\t", 1)
            mode, kind, sha = info.decode("ascii").split()
            path = name.decode("utf-8")
            if kind == "blob":
                self.files[path] = (mode, sha)
            parts = path.split("/")
            self.directories.update("/".join(parts[:i]) for i in range(1, len(parts)))
        self._data: dict[str, bytes] = {}

    def exists(self, path: str) -> bool:
        return path in self.files or path in self.directories

    def read(self, path: str) -> bytes:
        mode, sha = self.files[path]
        if mode not in {"100644", "100755"}:
            raise ValueError("Authored document/test is not a regular Git blob: " + path)
        if sha not in self._data:
            self._data[sha] = git(self.repo, "cat-file", "blob", sha)
        return self._data[sha]
