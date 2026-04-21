from __future__ import annotations
import networkx as nx
from app.schemas import CycleReport


def build_digraph(nodes: list[dict], edges: list[dict]) -> nx.DiGraph:
    G = nx.DiGraph()
    for n in nodes:
        G.add_node(n["id"])
    for e in edges:
        G.add_edge(e["source"], e["target"])
    return G


def detect_cycles(G: nx.DiGraph) -> tuple[CycleReport, set[str], set[tuple[str, str]]]:
    """
    Returns (CycleReport, cycle_node_ids, cycle_edge_pairs).
    cycle_edge_pairs: edges where BOTH endpoints are in the same SCC.
    """
    cycle_node_ids: set[str] = set()
    cycle_edge_pairs: set[tuple[str, str]] = set()
    sccs: list[list[str]] = []
    all_simple: list[list[str]] = []

    for scc in nx.strongly_connected_components(G):
        is_cycle = len(scc) > 1 or (
            len(scc) == 1 and G.has_edge(next(iter(scc)), next(iter(scc)))
        )
        if not is_cycle:
            continue

        sorted_scc = sorted(scc)
        sccs.append(sorted_scc)
        cycle_node_ids.update(scc)

        # Mark edges entirely within this SCC
        for u in scc:
            for v in G.successors(u):
                if v in scc:
                    cycle_edge_pairs.add((u, v))

        # Simple cycles — only on the subgraph, capped at 50
        sub = G.subgraph(scc).copy()
        for i, path in enumerate(nx.simple_cycles(sub)):
            if i >= 50:
                break
            all_simple.append(path)

    return (
        CycleReport(
            scc_count=len(sccs),
            node_count_in_cycles=len(cycle_node_ids),
            edge_count_in_cycles=len(cycle_edge_pairs),
            sccs=sccs,
            simple_cycles=all_simple,
        ),
        cycle_node_ids,
        cycle_edge_pairs,
    )


def annotate_graph(
    nodes: list[dict],
    edges: list[dict],
    cycle_node_ids: set[str],
    cycle_edge_pairs: set[tuple[str, str]],
) -> tuple[list[dict], list[dict]]:
    """Stamp is_cycle on every node and edge dict in-place, return them."""
    for n in nodes:
        n["is_cycle"] = n["id"] in cycle_node_ids
    for e in edges:
        e["is_cycle"] = (e["source"], e["target"]) in cycle_edge_pairs
    return nodes, edges
