"""
Heuristic setup instruction generator.
Scans the repo root (depth ≤ 2) for known manifests and produces SetupSteps.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from app.schemas import SetupSteps

logger = logging.getLogger(__name__)


def generate_setup(repo_root: Path, all_files: set[str]) -> SetupSteps:
    root_files = {Path(f).name for f in all_files if "/" not in f}
    depth2_files = set(all_files)  # all files up to any depth — good enough

    # ---- Detect primary runtime by manifest precedence ----
    if "package.json" in root_files:
        return _node_setup(repo_root, all_files)

    if "pyproject.toml" in root_files or "requirements.txt" in root_files or "Pipfile" in root_files:
        return _python_setup(repo_root, root_files)

    if "Cargo.toml" in root_files:
        return _rust_setup(repo_root, all_files)

    if "go.mod" in root_files:
        return _go_setup(repo_root, all_files)

    if "pom.xml" in root_files or "build.gradle" in root_files or "build.gradle.kts" in root_files:
        return _java_setup(repo_root, root_files)

    if "CMakeLists.txt" in root_files or "Makefile" in root_files:
        return _c_setup(repo_root, all_files)

    return SetupSteps(
        runtime="unknown",
        notes=["No recognized build manifest found."],
        env_vars=_extract_env_vars(repo_root, all_files),
    )


# ---------------------------------------------------------------------------
# Node / JS / TS
# ---------------------------------------------------------------------------

def _node_setup(repo_root: Path, all_files: set[str]) -> SetupSteps:
    pkg_data = _read_json(repo_root / "package.json") or {}
    scripts = pkg_data.get("scripts", {}) if isinstance(pkg_data, dict) else {}

    # Package manager detection
    root_files = {Path(f).name for f in all_files if "/" not in f}
    if "pnpm-lock.yaml" in root_files:
        pm = "pnpm"
    elif "yarn.lock" in root_files:
        pm = "yarn"
    elif "bun.lockb" in root_files:
        pm = "bun"
    else:
        pm = "npm"

    install_cmd = f"{pm} install"

    build_cmd = f"{pm} run build" if "build" in scripts else None

    if "dev" in scripts:
        run_cmd = f"{pm} run dev"
    elif "start" in scripts:
        run_cmd = f"{pm} start" if pm == "npm" else f"{pm} run start"
    else:
        run_cmd = None

    return SetupSteps(
        runtime="node",
        install_cmd=install_cmd,
        build_cmd=build_cmd,
        run_cmd=run_cmd,
        env_vars=_extract_env_vars(repo_root, all_files),
    )


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

def _python_setup(repo_root: Path, root_files: set[str]) -> SetupSteps:
    install_cmd: Optional[str] = None
    run_cmd: Optional[str] = None
    build_cmd: Optional[str] = None

    if "pyproject.toml" in root_files:
        text = _read_text(repo_root / "pyproject.toml") or ""
        if "[tool.poetry]" in text:
            install_cmd = "poetry install"
            run_cmd = _find_python_entrypoint(repo_root, prefix="poetry run python")
        else:
            install_cmd = "pip install -e ."
            run_cmd = _find_python_entrypoint(repo_root, prefix="python")
    elif "Pipfile" in root_files:
        install_cmd = "pipenv install"
        run_cmd = _find_python_entrypoint(repo_root, prefix="pipenv run python")
    elif "requirements.txt" in root_files:
        install_cmd = "pip install -r requirements.txt"
        run_cmd = _find_python_entrypoint(repo_root, prefix="python")

    return SetupSteps(
        runtime="python",
        install_cmd=install_cmd,
        build_cmd=build_cmd,
        run_cmd=run_cmd,
        env_vars=_extract_env_vars(repo_root, set()),
    )


def _find_python_entrypoint(repo_root: Path, prefix: str) -> Optional[str]:
    for name in ["main.py", "app.py", "manage.py", "__main__.py"]:
        if (repo_root / name).is_file():
            return f"{prefix} {name}"
    return None


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------

def _rust_setup(repo_root: Path, all_files: set[str]) -> SetupSteps:
    return SetupSteps(
        runtime="rust",
        install_cmd="cargo build",
        build_cmd="cargo build --release",
        run_cmd="cargo run",
        env_vars=_extract_env_vars(repo_root, all_files),
    )


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

def _go_setup(repo_root: Path, all_files: set[str]) -> SetupSteps:
    run_cmd: Optional[str] = None
    root_files = {Path(f).name for f in all_files if "/" not in f}
    if "main.go" in root_files:
        run_cmd = "go run ."
    else:
        # Look for cmd/ subdirectory
        cmd_subdirs = sorted({
            Path(f).parts[1]
            for f in all_files
            if f.startswith("cmd/") and len(Path(f).parts) >= 3
        })
        if cmd_subdirs:
            run_cmd = f"go run ./cmd/{cmd_subdirs[0]}"

    return SetupSteps(
        runtime="go",
        install_cmd="go mod download",
        build_cmd="go build ./...",
        run_cmd=run_cmd,
        env_vars=_extract_env_vars(repo_root, all_files),
    )


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------

def _java_setup(repo_root: Path, root_files: set[str]) -> SetupSteps:
    if "pom.xml" in root_files:
        return SetupSteps(
            runtime="java",
            install_cmd="mvn install",
            run_cmd="mvn exec:java",
            env_vars=_extract_env_vars(repo_root, set()),
        )
    return SetupSteps(
        runtime="java",
        install_cmd="./gradlew build",
        run_cmd="./gradlew run",
        env_vars=_extract_env_vars(repo_root, set()),
    )


# ---------------------------------------------------------------------------
# C / C++
# ---------------------------------------------------------------------------

def _c_setup(repo_root: Path, all_files: set[str]) -> SetupSteps:
    root_files = {Path(f).name for f in all_files if "/" not in f}
    has_cpp = any(f.endswith((".cpp", ".cc", ".cxx")) for f in all_files)
    runtime = "cpp" if has_cpp else "c"

    if "CMakeLists.txt" in root_files:
        return SetupSteps(
            runtime=runtime,
            build_cmd="cmake -B build && cmake --build build",
            env_vars=_extract_env_vars(repo_root, all_files),
        )
    return SetupSteps(
        runtime=runtime,
        install_cmd="make",
        env_vars=_extract_env_vars(repo_root, all_files),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENV_KEY_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)=", re.MULTILINE)


def _extract_env_vars(repo_root: Path, all_files: set[str]) -> list[str]:
    for name in [".env.example", ".env.sample", ".env.template"]:
        candidate = repo_root / name
        if candidate.is_file():
            text = _read_text(candidate) or ""
            return _ENV_KEY_RE.findall(text)
    return []


def _read_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(errors="replace")
        # Strip JS comments from package.json (some repos have them)
        text = re.sub(r"//.*", "", text)
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return json.loads(text)
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None
