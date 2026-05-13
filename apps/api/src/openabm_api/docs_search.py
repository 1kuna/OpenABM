from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]

PUBLIC_DOC_PATHS = [
    ROOT / "README.md",
    ROOT / "IMPLEMENTATION_PROGRESS.md",
    ROOT / "packages" / "shared-types" / "openapi" / "openapi.json",
]
PUBLIC_DOC_GLOBS = [
    ROOT / "packages" / "shared-types" / "schemas",
]
PRIVATE_PATH_NAMES = {"openabm_implementation_spec.md"}


def search_public_docs(query: str, *, limit: int = 20) -> dict[str, Any]:
    normalized_query = query.strip().lower()
    if not normalized_query:
        return {"query": query, "results": [], "searched_paths": _searched_path_names()}

    results: list[dict[str, Any]] = []
    for path in _public_files():
        for line_number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            score = _line_score(line, normalized_query)
            if score == 0:
                continue
            results.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "line": line_number,
                    "snippet": line.strip()[:500],
                    "score": score,
                    "reason": "exact_substring_match"
                    if normalized_query in line.lower()
                    else "token_overlap_match",
                }
            )

    results.sort(key=lambda item: (-int(item["score"]), item["path"], int(item["line"])))
    return {
        "query": query,
        "results": results[: max(1, limit)],
        "searched_paths": _searched_path_names(),
    }


def _public_files() -> list[Path]:
    paths = [path for path in PUBLIC_DOC_PATHS if _is_public_file(path)]
    for directory in PUBLIC_DOC_GLOBS:
        if directory.exists():
            paths.extend(
                path for path in sorted(directory.glob("*.schema.json")) if _is_public_file(path)
            )
    return sorted(set(paths))


def _is_public_file(path: Path) -> bool:
    return path.exists() and path.is_file() and path.name not in PRIVATE_PATH_NAMES


def _searched_path_names() -> list[str]:
    return [str(path.relative_to(ROOT)) for path in _public_files()]


def _line_score(line: str, normalized_query: str) -> int:
    line_lower = line.lower()
    if normalized_query in line_lower:
        return 100 + len(normalized_query)
    query_terms = {term for term in normalized_query.split() if len(term) > 2}
    if not query_terms:
        return 0
    matches = sum(1 for term in query_terms if term in line_lower)
    return matches if matches > 0 else 0
