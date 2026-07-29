"""Helpers for command executors to read skill-local environment files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def api_root_candidates(
    skill_dir: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    home_dir: str | Path | None = None,
) -> list[Path]:
    """Return explicit, monorepo, and legacy sibling API root candidates."""
    resolved_skill_dir = Path(skill_dir).expanduser().resolve()
    resolved_env = os.environ if env is None else env
    candidates: list[Path] = []

    env_root = resolved_env.get("STOCK_ANALYSIS_API_ROOT")
    if env_root:
        candidates.append(Path(env_root))

    # Installed in this repository:
    # <api-root>/.agents/skills/stock-analysis
    ancestors = [resolved_skill_dir, *list(resolved_skill_dir.parents)[:4]]
    candidates.extend(ancestors)

    # Compatibility for a separately installed skill next to stock-analysis-api.
    candidates.extend(ancestor / "stock-analysis-api" for ancestor in ancestors)
    if home_dir:
        candidates.append(Path(home_dir).expanduser() / "stock-analysis-api")

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _strip_wrapping_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    return key, _strip_wrapping_quotes(value)


def read_skill_env_file(skill_dir: str | Path) -> dict[str, str]:
    env_path = Path(skill_dir).expanduser().resolve() / ".env"
    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    parsed: dict[str, str] = {}
    for line in content.splitlines():
        parsed_line = _parse_env_line(line)
        if parsed_line is None:
            continue
        key, value = parsed_line
        parsed[key] = value
    return parsed


def effective_skill_env(
    skill_dir: str | Path,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    if env is not None:
        return dict(env)

    merged = read_skill_env_file(skill_dir)
    merged.update(os.environ)
    return merged
