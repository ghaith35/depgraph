"""
RepoContext — built once per /analyze request.
Holds all file lists and per-language indices needed by resolvers.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TsConfig:
    base_url: Optional[str]                    # relative to tsconfig's directory
    paths: dict[str, list[str]]                # alias → list of patterns
    dir: str                                   # directory containing this tsconfig


@dataclass
class RepoContext:
    repo_root: Path
    all_files: set[str]                        # all relative file paths (forward slashes)

    # Go
    go_module: str = ""                        # module path from go.mod

    # Java
    java_fqcn_index: dict[str, str] = field(default_factory=dict)   # FQCN → rel path
    java_package_of: dict[str, str] = field(default_factory=dict)   # rel path → package

    # TypeScript / JavaScript
    ts_configs: list[TsConfig] = field(default_factory=list)
    ts_workspace_aliases: dict[str, str] = field(default_factory=dict)  # pkg name → dir

    # Rust
    rust_mod_trees: dict[str, dict[str, str]] = field(default_factory=dict)
    # crate_root_file → {module_path ("foo::bar") → rel_file_path}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_context(repo_root: Path, all_files: set[str]) -> RepoContext:
    ctx = RepoContext(repo_root=repo_root, all_files=all_files)
    _build_go(ctx)
    _build_java(ctx)
    _build_ts(ctx)
    _build_rust(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Go — parse go.mod
# ---------------------------------------------------------------------------

def _build_go(ctx: RepoContext) -> None:
    gomod = ctx.repo_root / "go.mod"
    if not gomod.is_file():
        return
    try:
        for line in gomod.read_text(errors="replace").splitlines():
            m = re.match(r"^module\s+(\S+)", line)
            if m:
                ctx.go_module = m.group(1)
                return
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Java — build FQCN index
# ---------------------------------------------------------------------------

_JAVA_PKG_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)


def _build_java(ctx: RepoContext) -> None:
    for rel in ctx.all_files:
        if not rel.endswith(".java"):
            continue
        abs_path = ctx.repo_root / rel
        try:
            src = abs_path.read_text(errors="replace")
        except OSError:
            continue
        m = _JAVA_PKG_RE.search(src)
        pkg = m.group(1) if m else ""
        class_name = Path(rel).stem
        fqcn = f"{pkg}.{class_name}" if pkg else class_name
        ctx.java_fqcn_index[fqcn] = rel
        ctx.java_package_of[rel] = pkg


# ---------------------------------------------------------------------------
# TypeScript / JavaScript — tsconfig + workspaces
# ---------------------------------------------------------------------------

def _read_json_loose(path: Path) -> Optional[dict]:
    """Read JSON, stripping // comments (tsconfig uses JSON5-style comments)."""
    try:
        text = path.read_text(errors="replace")
        # Strip single-line comments
        text = re.sub(r"//.*", "", text)
        # Strip multi-line comments
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        # Remove trailing commas
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return json.loads(text)
    except Exception:
        return None


def _build_ts(ctx: RepoContext) -> None:
    # Workspace aliases from root package.json
    root_pkg = ctx.repo_root / "package.json"
    if root_pkg.is_file():
        data = _read_json_loose(root_pkg)
        if data:
            workspaces = data.get("workspaces", [])
            if isinstance(workspaces, dict):
                workspaces = workspaces.get("packages", [])
            _scan_workspaces(ctx, workspaces)

    # tsconfig files
    for rel in ctx.all_files:
        if Path(rel).name != "tsconfig.json":
            continue
        abs_path = ctx.repo_root / rel
        data = _read_json_loose(abs_path)
        if not data:
            continue
        compiler = data.get("compilerOptions", {})
        base_url = compiler.get("baseUrl")
        paths = compiler.get("paths", {})
        ts_dir = str(Path(rel).parent)
        ctx.ts_configs.append(TsConfig(
            base_url=base_url,
            paths={k: v for k, v in paths.items() if isinstance(v, list)},
            dir=ts_dir,
        ))

    # Sort: deeper paths first (more specific wins)
    ctx.ts_configs.sort(key=lambda c: -len(c.dir))


def _scan_workspaces(ctx: RepoContext, patterns: list) -> None:
    import fnmatch
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        for rel in ctx.all_files:
            if Path(rel).name != "package.json":
                continue
            pkg_dir = str(Path(rel).parent)
            if not fnmatch.fnmatch(pkg_dir, pattern.rstrip("/")):
                continue
            data = _read_json_loose(ctx.repo_root / rel)
            if not data:
                continue
            name = data.get("name", "")
            if name:
                ctx.ts_workspace_aliases[name] = pkg_dir


# ---------------------------------------------------------------------------
# Rust — build mod trees per crate
# ---------------------------------------------------------------------------

_MOD_RE = re.compile(r"^\s*(?:pub\s+)?mod\s+(\w+)\s*;", re.MULTILINE)


def _build_rust(ctx: RepoContext) -> None:
    # Find crate roots from Cargo.toml
    crate_roots: list[str] = []
    for rel in ctx.all_files:
        if Path(rel).name != "Cargo.toml":
            continue
        abs_path = ctx.repo_root / rel
        try:
            text = abs_path.read_text(errors="replace")
        except OSError:
            continue
        crate_dir = str(Path(rel).parent)
        prefix = "" if crate_dir == "." else crate_dir + "/"
        # Standard roots
        for candidate in ["src/lib.rs", "src/main.rs"]:
            full = f"{prefix}{candidate}"
            if full in ctx.all_files:
                crate_roots.append(full)
        # [[bin]] with custom path
        for m in re.finditer(r'path\s*=\s*"([^"]+\.rs)"', text):
            full = f"{prefix}{m.group(1)}"
            if full in ctx.all_files:
                crate_roots.append(full)

    for root_file in set(crate_roots):
        mod_tree: dict[str, str] = {}
        _walk_rust_mods(ctx, root_file, "crate", mod_tree)
        ctx.rust_mod_trees[root_file] = mod_tree


def _walk_rust_mods(
    ctx: RepoContext,
    file_rel: str,
    mod_path: str,
    tree: dict[str, str],
) -> None:
    tree[mod_path] = file_rel
    abs_path = ctx.repo_root / file_rel
    try:
        src = abs_path.read_text(errors="replace")
    except OSError:
        return
    file_dir = str(Path(file_rel).parent)
    for m in _MOD_RE.finditer(src):
        mod_name = m.group(1)
        child_path = mod_path + "::" + mod_name
        # Try file-based: <dir>/<mod>.rs or <dir>/<mod>/mod.rs
        candidates = [
            f"{file_dir}/{mod_name}.rs".lstrip("/"),
            f"{file_dir}/{mod_name}/mod.rs".lstrip("/"),
        ]
        for c in candidates:
            if c in ctx.all_files:
                _walk_rust_mods(ctx, c, child_path, tree)
                break
