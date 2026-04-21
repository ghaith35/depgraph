import { Edge, Node } from "./types";

const TEST_PATH_RE = /(^|\/)(__tests__|tests?|specs?)(\/|$)/i;
const TEST_FILE_RE = /\.(test|spec)\.[^.]+$/i;

export interface FilterState {
  hideTests: boolean;
  hideInfrastructure: boolean;
  onlyCycles: boolean;
  rendererOverride: "auto" | "svg" | "canvas" | "meta" | null;
}

export const DEFAULT_FILTERS: FilterState = {
  hideTests: false,
  hideInfrastructure: false,
  onlyCycles: false,
  rendererOverride: null,
};

/** Mark outlier hubs (high in-degree + large size) in-place on node objects. */
export function markOutlierHubs(nodes: Node[], edges: Edge[]): void {
  const inDegree = new Map<string, number>();
  for (const e of edges) {
    const t = typeof e.target === "string" ? e.target : (e.target as Node).id;
    inDegree.set(t, (inDegree.get(t) ?? 0) + 1);
  }
  const sortedSizes = nodes.map((n) => n.size).sort((a, b) => b - a);
  const topDecile =
    sortedSizes[Math.floor(sortedSizes.length * 0.1)] ?? Infinity;
  for (const n of nodes) {
    if ((inDegree.get(n.id) ?? 0) > 50 && n.size >= topDecile) {
      n.is_outlier_hub = true;
    }
  }
}

/** Return a filtered view of nodes/edges according to the current filter state. */
export function applyFilters(
  nodes: Node[],
  edges: Edge[],
  filters: FilterState,
): { nodes: Node[]; edges: Edge[] } {
  let fn = nodes;
  let fe = edges;

  if (filters.hideTests) {
    fn = fn.filter(
      (n) => !TEST_PATH_RE.test(n.id) && !TEST_FILE_RE.test(n.id),
    );
  }
  if (filters.hideInfrastructure) {
    fn = fn.filter((n) => !n.is_outlier_hub);
  }
  if (filters.onlyCycles) {
    fn = fn.filter((n) => n.is_cycle);
  }

  const visible = new Set(fn.map((n) => n.id));
  fe = fe.filter((e) => {
    const s = typeof e.source === "string" ? e.source : (e.source as Node).id;
    const t = typeof e.target === "string" ? e.target : (e.target as Node).id;
    return visible.has(s) && visible.has(t);
  });

  return { nodes: fn, edges: fe };
}
