"""Fail closed when production dependency lock drifts from project metadata."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PROD_LOCK = ROOT / "requirements-prod.lock"

_EXACT_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==(?P<version>[^\s;]+)$"
)
_LOCK_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s;]+)$"
)


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _parse_exact_requirement(value: str) -> tuple[str, str]:
    match = _EXACT_REQUIREMENT.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"runtime dependency is not an exact pin: {value!r}")
    return _canonical_name(match.group("name")), match.group("version")


def _load_lock() -> dict[str, str]:
    locked: dict[str, str] = {}
    for raw_line in PROD_LOCK.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-e ", "--", "http://", "https://", "git+")) or " @ " in line:
            raise ValueError(f"production lock contains a non-index dependency: {line!r}")
        match = _LOCK_REQUIREMENT.fullmatch(line)
        if match is None:
            raise ValueError(f"production lock line is not an exact pin: {line!r}")
        name = _canonical_name(match.group("name"))
        version = match.group("version")
        if name in locked:
            raise ValueError(f"production lock contains duplicate package: {name}")
        locked[name] = version
    if not locked:
        raise ValueError("production lock must not be empty")
    return locked


def main() -> int:
    with PYPROJECT.open("rb") as handle:
        project = tomllib.load(handle)

    dependencies = project.get("project", {}).get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("project.dependencies must be a non-empty list")

    direct = dict(_parse_exact_requirement(str(value)) for value in dependencies)
    locked = _load_lock()

    missing = sorted(name for name in direct if name not in locked)
    mismatched = sorted(
        f"{name}: project={direct[name]} lock={locked[name]}"
        for name in direct.keys() & locked.keys()
        if direct[name] != locked[name]
    )
    if missing or mismatched:
        details = [
            *(f"missing direct dependency in lock: {name}" for name in missing),
            *(f"version mismatch: {item}" for item in mismatched),
        ]
        raise ValueError("; ".join(details))

    print(
        "production dependency lock metadata check passed "
        f"({len(direct)} direct, {len(locked)} total packages)"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"dependency lock verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
