"""
Phase 4 — cycle detection + setup instructions tests.
Run with: pytest backend/tests/test_phase4.py -v
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import networkx as nx
from graph.builder import build_graph
from graph.cycles import build_digraph, detect_cycles, annotate_graph
from graph.setup import generate_setup

FIXTURES = Path(__file__).parent / "fixtures"


def _entries(fixture_dir: Path, exts=None):
    entries = []
    for p in sorted(fixture_dir.rglob("*")):
        if not p.is_file():
            continue
        if exts and p.suffix.lower() not in exts:
            continue
        rel = str(p.relative_to(fixture_dir))
        entries.append(SimpleNamespace(
            path=rel, size=p.stat().st_size, language_hint=p.suffix.lstrip(".") or "other",
        ))
    return entries


def _build(fix_name, exts=None):
    fix = FIXTURES / fix_name
    entries = _entries(fix, exts)
    raw = build_graph(fix, entries)
    G = build_digraph(raw["nodes"], raw["edges"])
    report, node_ids, edge_pairs = detect_cycles(G)
    annotate_graph(raw["nodes"], raw["edges"], node_ids, edge_pairs)
    return raw, report


# ---------------------------------------------------------------------------
# Test A — 3-file cycle
# ---------------------------------------------------------------------------

def test_cycle_three():
    raw, report = _build("cycle_three", {".py"})
    assert report.scc_count == 1
    assert report.sccs == [["a.py", "b.py", "c.py"]]

    node_map = {n["id"]: n for n in raw["nodes"]}
    assert node_map["a.py"]["is_cycle"] is True
    assert node_map["b.py"]["is_cycle"] is True
    assert node_map["c.py"]["is_cycle"] is True

    for e in raw["edges"]:
        assert e["is_cycle"] is True, f"Edge {e['source']}→{e['target']} should be cycle"

    assert len(report.simple_cycles) == 1


# ---------------------------------------------------------------------------
# Test B — two disjoint cycles {a,b} and {c,d,e}
# ---------------------------------------------------------------------------

def test_cycle_two_disjoint():
    raw, report = _build("cycle_two_disjoint", {".py"})
    assert report.scc_count == 2
    scc_sizes = sorted(len(s) for s in report.sccs)
    assert scc_sizes == [2, 3], f"Expected SCCs of size 2 and 3, got {scc_sizes}"


# ---------------------------------------------------------------------------
# Test C — cycle node connecting to non-cycle node
# ---------------------------------------------------------------------------

def test_cycle_with_external_edge():
    # Build inline: a→b, b→a (cycle), a→c (c not in cycle)
    nodes = [{"id": "a.py"}, {"id": "b.py"}, {"id": "c.py"}]
    edges = [
        {"source": "a.py", "target": "b.py"},
        {"source": "b.py", "target": "a.py"},
        {"source": "a.py", "target": "c.py"},
    ]
    G = build_digraph(nodes, edges)
    report, node_ids, edge_pairs = detect_cycles(G)
    annotate_graph(nodes, edges, node_ids, edge_pairs)

    node_map = {n["id"]: n for n in nodes}
    assert node_map["a.py"]["is_cycle"] is True
    assert node_map["b.py"]["is_cycle"] is True
    assert node_map["c.py"]["is_cycle"] is False

    edge_map = {(e["source"], e["target"]): e for e in edges}
    assert edge_map[("a.py", "b.py")]["is_cycle"] is True
    assert edge_map[("b.py", "a.py")]["is_cycle"] is True
    assert edge_map[("a.py", "c.py")]["is_cycle"] is False


# ---------------------------------------------------------------------------
# Test D — self-cycle
# ---------------------------------------------------------------------------

def test_self_cycle():
    nodes = [{"id": "x.py"}]
    edges = [{"source": "x.py", "target": "x.py"}]
    G = build_digraph(nodes, edges)
    report, node_ids, edge_pairs = detect_cycles(G)
    assert report.scc_count == 1
    assert "x.py" in node_ids


# ---------------------------------------------------------------------------
# Test E — Python setup with requirements.txt
# ---------------------------------------------------------------------------

def test_setup_python():
    fix = FIXTURES / "setup_python"
    all_files = {str(p.relative_to(fix)) for p in fix.rglob("*") if p.is_file()}
    setup = generate_setup(fix, all_files)
    assert setup.runtime == "python"
    assert setup.install_cmd == "pip install -r requirements.txt"
    assert setup.run_cmd == "python main.py"


# ---------------------------------------------------------------------------
# Test F — Node project with pnpm
# ---------------------------------------------------------------------------

def test_setup_node_pnpm():
    fix = FIXTURES / "setup_node"
    all_files = {str(p.relative_to(fix)) for p in fix.rglob("*") if p.is_file()}
    setup = generate_setup(fix, all_files)
    assert setup.runtime == "node"
    assert setup.install_cmd == "pnpm install"
    assert setup.run_cmd == "pnpm run dev"
    assert setup.build_cmd == "pnpm run build"


# ---------------------------------------------------------------------------
# Test G — .env.example extraction
# ---------------------------------------------------------------------------

def test_env_vars():
    fix = FIXTURES / "setup_env"
    all_files = {str(p.relative_to(fix)) for p in fix.rglob("*") if p.is_file()}
    setup = generate_setup(fix, all_files)
    assert setup.env_vars == ["DATABASE_URL", "API_KEY", "DEBUG"]
