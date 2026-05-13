from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".openabm",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "artifacts",
    "node_modules",
}


def main() -> int:
    failures: list[str] = []
    for path in _markdown_files():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for target in LINK_PATTERN.findall(line):
                resolved = _resolve_doc_link(path, target)
                if resolved is None:
                    continue
                if not resolved.exists():
                    failures.append(
                        f"{path.relative_to(ROOT)}:{line_number}: missing link target {target}"
                    )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


def _markdown_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        files.append(path)
    return sorted(files)


def _resolve_doc_link(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip()
    if not target or target.startswith("#"):
        return None
    parsed = urlparse(target)
    if parsed.scheme or target.startswith(("mailto:", "tel:")):
        return None
    path_part = parsed.path.split("#", 1)[0]
    if not path_part:
        return None
    if path_part.startswith("/"):
        return ROOT / path_part.removeprefix("/")
    return source.parent / path_part


if __name__ == "__main__":
    raise SystemExit(main())
