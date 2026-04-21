"""
Phase 2 — Python resolver tests.
Run with: pytest backend/tests/test_python_resolver.py -v
"""
import sys
from pathlib import Path

# Make sure backend/ is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.builder import build_graph

FIXTURE = Path(__file__).parent / "fixtures" / "python_simple"


def _make_file_entries():
    """Build minimal FileEntry-like objects from the fixture directory."""
    from types import SimpleNamespace
    entries = []
    for p in sorted(FIXTURE.rglob("*.py")):
        rel = str(p.relative_to(FIXTURE))
        entries.append(SimpleNamespace(
            path=rel,
            size=p.stat().st_size,
            language_hint="python",
        ))
    return entries


def test_graph_fixture():
    entries = _make_file_entries()
    result = build_graph(FIXTURE, entries)
    nodes = result["nodes"]
    edges = result["edges"]

    node_ids = {n["id"] for n in nodes}
    edge_pairs = {(e["source"], e["target"]) for e in edges}

    # All 5 files appear as nodes
    assert "main.py" in node_ids
    assert "helpers.py" in node_ids
    assert "utils/__init__.py" in node_ids
    assert "utils/io.py" in node_ids
    assert "orphan.py" in node_ids

    # Assertion 1: main.py → helpers.py
    assert ("main.py", "helpers.py") in edge_pairs, \
        f"Missing main.py→helpers.py. Got edges: {edge_pairs}"

    # Assertion 2: main.py → utils/__init__.py
    assert ("main.py", "utils/__init__.py") in edge_pairs, \
        f"Missing main.py→utils/__init__.py. Got edges: {edge_pairs}"

    # Assertion 3: utils/io.py → helpers.py (relative .. resolved)
    assert ("utils/io.py", "helpers.py") in edge_pairs, \
        f"Missing utils/io.py→helpers.py. Got edges: {edge_pairs}"

    # Assertion 4: utils/__init__.py → utils/io.py
    assert ("utils/__init__.py", "utils/io.py") in edge_pairs, \
        f"Missing utils/__init__.py→utils/io.py. Got edges: {edge_pairs}"

    # Assertion 5: orphan.py has no edges
    orphan_edges = [e for e in edges if e["source"] == "orphan.py" or e["target"] == "orphan.py"]
    assert orphan_edges == [], f"orphan.py should have no edges, got: {orphan_edges}"

    # Assertion 6: exact edge count = 4
    assert len(edges) == 4, f"Expected exactly 4 edges, got {len(edges)}: {edge_pairs}"

    print(f"\nAll assertions passed. nodes={len(nodes)} edges={len(edges)}")
    for e in edges:
        print(f"  {e['source']} → {e['target']}  line={e['line']} symbol={e['symbol']}")
