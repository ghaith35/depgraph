import { Edge, Node } from "./types";

/** A meta-node represents one directory cluster. */
export interface MetaNode extends Node {
  kind: "meta";
  file_count: number;
  members: Node[];
}

function dominantLanguage(members: Node[]): string {
  const counts = new Map<string, number>();
  for (const n of members) {
    counts.set(n.language, (counts.get(n.language) ?? 0) + 1);
  }
  let best = "other";
  let bestN = 0;
  for (const [lang, n] of counts) {
    if (n > bestN) {
      best = lang;
      bestN = n;
    }
  }
  return best;
}

function edgeNodeId(n: string | Node): string {
  return typeof n === "string" ? n : n.id;
}

/** Collapse nodes into per-cluster meta-nodes + inter-cluster edges. */
export function buildMetaGraph(
  nodes: Node[],
  edges: Edge[],
): { metaNodes: MetaNode[]; metaEdges: Edge[] } {
  const byCluster = new Map<string, Node[]>();
  for (const n of nodes) {
    const key = n.cluster || "(root)";
    const arr = byCluster.get(key) ?? [];
    arr.push(n);
    byCluster.set(key, arr);
  }

  const metaNodes: MetaNode[] = Array.from(byCluster, ([cluster, members]) => ({
    id: cluster,
    label: cluster.split("/").pop() ?? cluster, // last path segment
    language: dominantLanguage(members),
    size: Math.round(Math.sqrt(members.reduce((s, n) => s + n.size, 0))),
    is_cycle: members.some((m) => m.is_cycle),
    cluster,
    kind: "meta" as const,
    file_count: members.length,
    members,
  }));

  const nodeCluster = new Map(nodes.map((n) => [n.id, n.cluster || "(root)"]));
  const edgeCount = new Map<string, number>();
  const cycleKeys = new Set<string>();

  for (const e of edges) {
    const sc = nodeCluster.get(edgeNodeId(e.source));
    const tc = nodeCluster.get(edgeNodeId(e.target));
    if (!sc || !tc || sc === tc) continue;
    const key = `${sc}|||${tc}`;
    edgeCount.set(key, (edgeCount.get(key) ?? 0) + 1);
    if (e.is_cycle) cycleKeys.add(key);
  }

  const metaEdges: Edge[] = Array.from(edgeCount, ([key, _weight]) => {
    const [source, target] = key.split("|||");
    return {
      source,
      target,
      symbol: null,
      line: 0,
      is_cycle: cycleKeys.has(key),
      has_dynamic_target: false,
    };
  });

  return { metaNodes, metaEdges };
}

/**
 * Build the "display graph" for the meta-graph view.
 * Non-expanded clusters → single meta-node.
 * Expanded clusters → their individual member nodes.
 * Edges are remapped so both endpoints are always a visible node.
 */
export function buildDisplayGraph(
  nodes: Node[],
  edges: Edge[],
  metaNodes: MetaNode[],
  expandedClusters: Set<string>,
): { displayNodes: Node[]; displayEdges: Edge[] } {
  const metaByCluster = new Map(metaNodes.map((m) => [m.cluster, m]));

  // Collect display nodes
  const displayNodes: Node[] = [];
  for (const mn of metaNodes) {
    if (expandedClusters.has(mn.cluster)) {
      displayNodes.push(...mn.members);
    } else {
      displayNodes.push(mn);
    }
  }

  const visibleIds = new Set(displayNodes.map((n) => n.id));

  // Map a file node id to the id that is visible (meta-node or itself)
  const fileCluster = new Map(nodes.map((n) => [n.id, n.cluster || "(root)"]));
  function resolveId(fileId: string): string | null {
    const cluster = fileCluster.get(fileId);
    if (!cluster) return null;
    if (expandedClusters.has(cluster)) return fileId; // individual node visible
    const meta = metaByCluster.get(cluster);
    return meta ? meta.id : null;
  }

  const seenEdges = new Set<string>();
  const displayEdges: Edge[] = [];

  for (const e of edges) {
    const rawS = edgeNodeId(e.source);
    const rawT = edgeNodeId(e.target);
    const s = resolveId(rawS);
    const t = resolveId(rawT);
    if (!s || !t || s === t) continue;
    if (!visibleIds.has(s) || !visibleIds.has(t)) continue;
    const key = `${s}→${t}`;
    if (seenEdges.has(key)) continue;
    seenEdges.add(key);
    displayEdges.push({ ...e, source: s, target: t });
  }

  return { displayNodes, displayEdges };
}
