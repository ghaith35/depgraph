"""
Phase 3 — multi-language resolver tests.
Run with: pytest backend/tests/test_phase3.py -v
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.builder import build_graph

FIXTURES = Path(__file__).parent / "fixtures"


def _entries(fixture_dir: Path, exts: set[str] | None = None) -> list:
    entries = []
    for p in sorted(fixture_dir.rglob("*")):
        if not p.is_file():
            continue
        if exts and p.suffix.lower() not in exts:
            continue
        rel = str(p.relative_to(fixture_dir))
        entries.append(SimpleNamespace(
            path=rel,
            size=p.stat().st_size,
            language_hint=p.suffix.lstrip(".") or "other",
        ))
    return entries


# ---------------------------------------------------------------------------
# JS CommonJS
# ---------------------------------------------------------------------------

def test_js_commonjs():
    fix = FIXTURES / "js_commonjs"
    entries = _entries(fix, {".js"})
    result = build_graph(fix, entries)
    pairs = {(e["source"], e["target"]) for e in result["edges"]}
    node_ids = {n["id"] for n in result["nodes"]}

    # index.js → utils.js
    assert ("index.js", "utils.js") in pairs, f"Missing index→utils. Edges: {pairs}"
    # index.js → lib/helper.js (extension probe)
    assert ("index.js", "lib/helper.js") in pairs, f"Missing index→lib/helper. Edges: {pairs}"
    # lib/helper.js → utils.js (../ relative)
    assert ("lib/helper.js", "utils.js") in pairs, f"Missing lib/helper→utils. Edges: {pairs}"
    # orphan.js has no edges
    orphan_edges = [e for e in result["edges"] if "orphan" in e["source"] or "orphan" in e["target"]]
    assert not orphan_edges, f"orphan should have no edges: {orphan_edges}"
    # external require('express') → no edge
    express_edges = [e for e in result["edges"] if "express" in str(e)]
    assert not express_edges


# ---------------------------------------------------------------------------
# TypeScript monorepo
# ---------------------------------------------------------------------------

def test_ts_monorepo():
    fix = FIXTURES / "ts_monorepo"
    entries = _entries(fix, {".ts", ".tsx", ".json"})
    result = build_graph(fix, entries)
    pairs = {(e["source"], e["target"]) for e in result["edges"]}

    main = "packages/web/src/main.ts"

    # main.ts → packages/web/src/lib/x.ts (via @/* paths alias)
    assert (main, "packages/web/src/lib/x.ts") in pairs, \
        f"Missing paths alias edge. Edges from main: {[e for e in result['edges'] if e['source'] == main]}"

    # main.ts → packages/shared/src/index.ts (via workspace alias)
    assert (main, "packages/shared/src/index.ts") in pairs, \
        f"Missing workspace alias edge. Edges from main: {[e for e in result['edges'] if e['source'] == main]}"

    # shared/src/index.ts → shared/src/utils.ts (relative)
    assert ("packages/shared/src/index.ts", "packages/shared/src/utils.ts") in pairs, \
        f"Missing shared internal edge. All edges: {pairs}"


# ---------------------------------------------------------------------------
# Java wildcard
# ---------------------------------------------------------------------------

def test_java_wildcard():
    fix = FIXTURES / "java_wildcard"
    entries = _entries(fix, {".java"})
    result = build_graph(fix, entries)
    pairs = {(e["source"], e["target"]) for e in result["edges"]}

    app = "src/com/example/App.java"
    logger = "src/com/utils/Logger.java"
    helper = "src/com/utils/Helper.java"
    service = "src/com/example/Service.java"

    # App wildcard import com.utils.* → both Logger and Helper
    assert (app, logger) in pairs, f"Missing App→Logger. Edges: {pairs}"
    assert (app, helper) in pairs, f"Missing App→Helper. Edges: {pairs}"
    # App direct import com.utils.Logger → Logger (already covered but check no duplicate)
    # Service → Logger
    assert (service, logger) in pairs, f"Missing Service→Logger. Edges: {pairs}"


# ---------------------------------------------------------------------------
# Go module
# ---------------------------------------------------------------------------

def test_go_module():
    fix = FIXTURES / "go_module"
    entries = _entries(fix, {".go", ""})  # include go.mod as non-parseable
    # Only .go files matter for parsing
    entries = [e for e in entries if e.path.endswith(".go")]
    result = build_graph(fix, entries)
    pairs = {(e["source"], e["target"]) for e in result["edges"]}

    cmd_main = "cmd/main.go"
    auth_go = "internal/auth/auth.go"
    auth_utils = "internal/auth/utils.go"

    # cmd/main.go imports internal/auth → edges to all .go files in that package
    auth_edges = [(s, t) for s, t in pairs if s == cmd_main and "auth" in t]
    assert auth_edges, f"No edges from cmd/main.go to auth package. Edges: {pairs}"
    # stdlib "fmt" → no edge
    fmt_edges = [e for e in result["edges"] if "fmt" in str(e)]
    assert not fmt_edges


# ---------------------------------------------------------------------------
# Rust mod tree
# ---------------------------------------------------------------------------

def test_rust_modtree():
    fix = FIXTURES / "rust_modtree"
    # Include Cargo.toml so build_context can find crate roots
    entries = _entries(fix)
    result = build_graph(fix, entries)
    pairs = {(e["source"], e["target"]) for e in result["edges"]}

    main_rs = "src/main.rs"
    bar_rs = "src/foo/bar.rs"
    utils_rs = "src/foo/utils.rs"

    # main.rs uses crate::foo::bar::helper → src/foo/bar.rs
    assert (main_rs, bar_rs) in pairs, f"Missing main→bar. Edges: {pairs}"
    # main.rs uses crate::foo::utils → src/foo/utils.rs
    assert (main_rs, utils_rs) in pairs, f"Missing main→utils. Edges: {pairs}"
    # bar.rs uses super::utils → src/foo/utils.rs
    assert (bar_rs, utils_rs) in pairs, f"Missing bar→utils. Edges: {pairs}"


# ---------------------------------------------------------------------------
# C local headers
# ---------------------------------------------------------------------------

def test_c_headers():
    fix = FIXTURES / "c_local_headers"
    entries = _entries(fix, {".c", ".h"})
    result = build_graph(fix, entries)
    pairs = {(e["source"], e["target"]) for e in result["edges"]}

    # main.c → include/utils.h (probe: same dir miss, then include/ hit)
    assert ("main.c", "include/utils.h") in pairs, f"Missing main→utils.h. Edges: {pairs}"
    # main.c → helpers.h (same dir)
    assert ("main.c", "helpers.h") in pairs, f"Missing main→helpers.h. Edges: {pairs}"
    # utils.c → include/utils.h
    assert ("utils.c", "include/utils.h") in pairs, f"Missing utils.c→utils.h. Edges: {pairs}"
    # <stdio.h> system include → no edge
    stdio_edges = [e for e in result["edges"] if "stdio" in str(e)]
    assert not stdio_edges
