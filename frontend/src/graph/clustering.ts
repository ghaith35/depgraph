import { Node } from "./types";

export function buildClusterCentroids(
  nodes: Node[],
  width: number,
  height: number,
): Map<string, { x: number; y: number }> {
  const clusters = [...new Set(nodes.map((n) => n.cluster))];
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.3;
  const map = new Map<string, { x: number; y: number }>();
  clusters.forEach((c, i) => {
    const a = (i / clusters.length) * 2 * Math.PI;
    map.set(c, { x: cx + radius * Math.cos(a), y: cy + radius * Math.sin(a) });
  });
  return map;
}

/** Custom D3 force that nudges each node toward its cluster centroid. */
export function makeClusterForce(
  centroids: Map<string, { x: number; y: number }>,
  strength = 0.15,
) {
  let _nodes: Node[] = [];

  function force(alpha: number) {
    for (const n of _nodes) {
      const c = centroids.get(n.cluster);
      if (!c) continue;
      n.vx = (n.vx ?? 0) + (c.x - (n.x ?? 0)) * strength * alpha;
      n.vy = (n.vy ?? 0) + (c.y - (n.y ?? 0)) * strength * alpha;
    }
  }

  force.initialize = (ns: Node[]) => {
    _nodes = ns;
  };

  return force;
}
