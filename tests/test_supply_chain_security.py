from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PYPROJECT = ROOT / "pyproject.toml"
PROD_LOCK = ROOT / "requirements-prod.lock"
BUILD_LOCK = ROOT / "requirements-build.lock"

ACTION_SHA = re.compile(r"^\s*uses:\s*[^@\s]+@([0-9a-f]{40})(?:\s+#.*)?$")
EXACT_PIN = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s;]+$")
LOCK_PIN = re.compile(r"^[A-Za-z0-9_.-]+==[^\s;]+$")


def _workflow_files() -> list[Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def _meaningful_lock_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_all_github_actions_are_pinned_to_full_commit_sha() -> None:
    workflows = _workflow_files()
    assert workflows

    uses_lines: list[str] = []
    for workflow in workflows:
        uses_lines.extend(
            line for line in workflow.read_text(encoding="utf-8").splitlines() if "uses:" in line
        )

    assert uses_lines
    assert all(ACTION_SHA.fullmatch(line) for line in uses_lines)


def test_ci_keeps_read_only_token_and_nonpersistent_checkout_credentials() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in ci
    assert "persist-credentials: false" in ci
    assert "secrets." not in ci


def test_ci_keeps_supply_chain_gates_enabled() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    required_markers = (
        "python scripts/verify_prod_lock.py",
        "python -m pip check",
        "pip_audit --progress-spinner off -r requirements-prod.lock",
        "pip_audit --progress-spinner off -r requirements-build.lock",
        "pip_audit --local --skip-editable --progress-spinner off",
        "diff -u /tmp/expected-prod.lock /tmp/resolved-prod.lock",
    )
    assert all(marker in ci for marker in required_markers)


def test_project_runtime_and_build_dependencies_are_exactly_pinned() -> None:
    with PYPROJECT.open("rb") as handle:
        config = tomllib.load(handle)

    build_requires = config["build-system"]["requires"]
    runtime = config["project"]["dependencies"]
    dev = config["project"]["optional-dependencies"]["dev"]
    security = config["project"]["optional-dependencies"]["security"]

    assert build_requires
    assert runtime
    assert dev
    assert security
    assert all(EXACT_PIN.fullmatch(value) for value in build_requires)
    assert all(EXACT_PIN.fullmatch(value) for value in runtime)
    assert all(EXACT_PIN.fullmatch(value) for value in dev)
    assert all(EXACT_PIN.fullmatch(value) for value in security)


def test_lock_files_contain_only_exact_index_pins() -> None:
    for path in (PROD_LOCK, BUILD_LOCK):
        lines = _meaningful_lock_lines(path)
        assert lines
        assert all(LOCK_PIN.fullmatch(line) for line in lines)
        assert not any(" @ " in line or "://" in line or line.startswith("-e ") for line in lines)
        names = [re.split(r"==", line, maxsplit=1)[0].lower() for line in lines]
        assert len(names) == len(set(names))


def test_pytest_pin_is_past_recorded_phase17_advisory_floor() -> None:
    with PYPROJECT.open("rb") as handle:
        config = tomllib.load(handle)

    dev = config["project"]["optional-dependencies"]["dev"]
    assert "pytest==9.1.1" in dev
