# DepGraph — Phase 7: Canvas Fallback + Clustering for Large Graphs

## Goal
Handle repos with hundreds to thousands of files without the graph becoming unusable. Below 300 nodes, the SVG path from Phase 6 works fine. Above that, switch rendering strategies.

## Time budget
3 hours.

## Prerequisites
Phase 6 complete. SVG force-directed graph working for small repos.

---

## Strategy ladder

| Node count | Renderer | Labels | Layout |
|------------|----------|--------|--------|
| 0–300 | SVG | Always | Standard forces |
| 300–800 | SVG | Show on hover + above 1.5× zoom | Standard forces + cluster force |
| 800–1500 | Canvas | Hover only | Standard forces + cluster force |
| >1500 | Canvas | Hover only | **Meta-graph** (cluster-as-node) |

A user-facing toggle can override these thresholds manually.

---

## Part 1: Canvas renderer

At 800+ nodes, SVG repaint dominates — each tick, the browser recalculates layout for hundreds of DOM elements. Canvas draws everything in a small number of `ctx` calls per tick, no DOM churn.

### Key decisions
- Use **HiDPI-correct sizing**: set `canvas.width = clientWidth * devicePixelRatio`, then `ctx.scale(dpr, dpr)`. Without this, canvas is blurry on Retina/high-DPI screens.
- **Hit-testing via `d3.quadtree`** — rebuild every 5 ticks (not every tick — too expensive).
- **Transform stored in a `useRef`**, not React state. Zoom/pan must not trigger React re-renders.
- **Line widths and dash intervals scale inversely to zoom** (divide by `transform.k`) so visual weight stays consistent.

### Component outline

```tsx
export function CanvasGraphCanvas({ nodes, edges, onNodeSelect, selectedNodeId }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const simulationRef = useRef<d3.Simulation<Node, Edge> | null>(null);
  const quadtreeRef = useRef<d3.Quadtree<Node> | null>(null);
  const transformRef = useRef(d3.zoomIdentity);
  const hoveredRef = useRef<Node | null>(null);

  // Setup effect (runs once):
  // - Configure HiDPI canvas
  // - Create simulation (same forces as SVG version)
  // - Attach zoom behavior to canvas element
  // - Attach mousemove/click listeners for hit-testing
  // - sim.on("tick") calls draw()
  // - sim.on("tick.quadtree") rebuilds quadtree every 5 ticks

  // Data update effect (on nodes/edges change):
  // - sim.nodes(nodes); sim.force("link").links(edges); sim.alpha(0.3).restart()
  //   (same incremental update pattern as Phase 6)
  return <canvas ref={canvasRef} />;
}
```

### The draw function

```ts
function draw(ctx, nodes, edges, width, height, transform, hovered, selectedId) {
  ctx.save();
  ctx.clearRect(0, 0, width, height);
  ctx.translate(transform.x, transform.y);
  ctx.scale(transform.k, transform.k);

  // Edges first (under nodes)
  for (const e of edges) {
    const src = e.source as any, tgt = e.target as any;
    if (!src?.x || !tgt?.x) continue;
    ctx.strokeStyle = e.is_cycle ? "#e11d48" : "rgba(153,153,153,0.6)";
    ctx.lineWidth = (e.is_cycle ? 2 : 1) / transform.k;
    ctx.setLineDash(e.has_dynamic_target ? [4/transform.k, 4/transform.k] : []);
    ctx.beginPath();
    ctx.moveTo(src.x, src.y);
    ctx.lineTo(tgt.x, tgt.y);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  // Nodes on top
  for (const n of nodes) {
    if (!n.x) continue;
    const r = nodeRadius(n);
    ctx.fillStyle = languageColor(n.language);
    ctx.strokeStyle = n.id === selectedId ? "#2563eb"
                    : n === hovered ? "#1f2937"
                    : n.is_cycle ? "#e11d48" : "#fff";
    ctx.lineWidth = (n.id === selectedId ? 4 : n.is_cycle ? 3 : 1.5) / transform.k;
    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
    ctx.fill();
    ctx.stroke();
  }

  // Hovered label only
  if (hovered) {
    ctx.fillStyle = "#1f2937";
    ctx.font = `${12/transform.k}px sans-serif`;
    ctx.textAlign = "center";
    ctx.fillText(hovered.label, hovered.x, hovered.y + nodeRadius(hovered) + 14/transform.k);
  }
  ctx.restore();
}
```

### Screen-to-world coordinate translation

```ts
function screenToWorld(event, canvas, transform) {
  const rect = canvas.getBoundingClientRect();
  const sx = event.clientX - rect.left;
  const sy = event.clientY - rect.top;
  return {
    x: (sx - transform.x) / transform.k,
    y: (sy - transform.y) / transform.k,
  };
}
```

### Renderer dispatch in parent component

```tsx
function GraphView({ nodes, edges, rendererOverride, ... }) {
  const auto = nodes.length >= 1500 ? "meta"
             : nodes.length >= 800 ? "canvas"
             : "svg";
  const mode = rendererOverride ?? auto;
  switch (mode) {
    case "meta":   return <MetaGraph nodes={nodes} edges={edges} ... />;
    case "canvas": return <CanvasGraphCanvas nodes={nodes} edges={edges} ... />;
    default:       return <GraphCanvas nodes={nodes} edges={edges} ... />;
  }
}
```

---

## Part 2: Clustering force (300+ nodes)

Each node's `cluster` attribute is the repo-relative directory at depth 2 (e.g., `src/auth`). Compute a centroid per unique cluster, arranged in a circle around the viewport center. Apply a weak radial force toward each node's centroid.

```ts
function buildClusterCentroids(nodes, width, height) {
  const clusters = Array.from(new Set(nodes.map(n => n.cluster)));
  const cx = width / 2, cy = height / 2;
  const radius = Math.min(width, height) * 0.3;
  const map = new Map();
  clusters.forEach((c, i) => {
    const a = (i / clusters.length) * 2 * Math.PI;
    map.set(c, { x: cx + radius * Math.cos(a), y: cy + radius * Math.sin(a) });
  });
  return map;
}

function clusterForce(centroids, strength = 0.15) {
  return function (alpha) {
    for (const n of this.nodes()) {
      const c = centroids.get(n.cluster);
      if (!c) continue;
      n.vx += (c.x - n.x) * strength * alpha;
      n.vy += (c.y - n.y) * strength * alpha;
    }
  };
}
```

Register: `sim.force("cluster", clusterForce(centroids))`.

When clustering is active, reduce charge strength to prevent double-repulsion: `sim.force("charge", d3.forceManyBody().strength(-150))`.

---

## Part 3: Meta-graph mode (1500+ nodes)

Render one node per cluster instead of one per file. File-level detail available on-demand by expanding individual clusters.

### Building the meta-graph

```ts
function buildMetaGraph(nodes, edges) {
  // Group by cluster
  const byCluster = new Map<string, Node[]>();
  for (const n of nodes) {
    const arr = byCluster.get(n.cluster) ?? [];
    arr.push(n);
    byCluster.set(n.cluster, arr);
  }

  const metaNodes = Array.from(byCluster, ([cluster, members]) => ({
    id: cluster,
    label: cluster,
    size: members.reduce((s, n) => s + n.size, 0),
    language: dominantLanguage(members),
    file_count: members.length,
    is_cycle: members.some(m => m.is_cycle),
    members,
  }));

  // Aggregate inter-cluster edges by count
  const edgeCount = new Map<string, number>();
  const nodeIndex = new Map(nodes.map(n => [n.id, n]));
  for (const e of edges) {
    const src = nodeIndex.get(e.source as string);
    const tgt = nodeIndex.get(e.target as string);
    if (!src || !tgt || src.cluster === tgt.cluster) continue;
    const key = `${src.cluster}|${tgt.cluster}`;
    edgeCount.set(key, (edgeCount.get(key) ?? 0) + 1);
  }

  const metaEdges = Array.from(edgeCount, ([key, weight]) => {
    const [source, target] = key.split("|");
    return { source, target, weight };
  });

  return { metaNodes, metaEdges };
}
```

### Meta-node visuals
- Size: `sqrt(total_loc)`, clamped 20–80 px.
- Color: the dominant language in the cluster (by file count).
- Label: cluster name (directory path).
- Small badge showing file count: "47 files".
- Meta-edge width: `1 + log(weight)`.

### Click-to-expand
Maintain `expandedClusters: Set<string>` in state. The rendered graph is: meta-nodes for every NOT-expanded cluster, plus individual nodes from every expanded cluster, plus edges whose both endpoints are currently visible (either as meta-nodes or expanded nodes). Crossing edges become meta→meta, meta→node, node→meta, or node→node depending on which side is expanded.

Animation: when a cluster is expanded, briefly give its child nodes a position near the meta-node's last position, then let the force layout spread them. Use `sim.alpha(0.5).restart()` to kick the simulation.

### Collapse affordance
Small "×" button floating above the centroid of each expanded cluster. Clicking collapses it back to meta-node form.

---

## Part 4: Outlier hub handling (from plan §9.5)

Some files (autogenerated types, massive minified bundles, shared constants) are imported by 50+ other files, dominating graph layout. Detect and visually separate.

```ts
function markOutlierHubs(nodes, edges) {
  const inDegree = new Map();
  for (const e of edges) {
    inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
  }
  const sortedSizes = nodes.map(n => n.size).sort((a, b) => b - a);
  const topDecile = sortedSizes[Math.floor(sortedSizes.length * 0.1)] ?? Infinity;
  for (const n of nodes) {
    if ((inDegree.get(n.id) ?? 0) > 50 && n.size >= topDecile) {
      n.is_outlier_hub = true;
    }
  }
}
```

Rendering for outlier hubs:
- Pinned via `fx`/`fy` to the bottom-right corner — don't participate in force layout.
- Render in muted gray regardless of language color.
- Edges to them at opacity 0.2 instead of 0.6.
- User toggle: "Hide infrastructure files" removes them and their edges entirely.

---

## Part 5: Filters and user controls

Floating control panel in the top-right of the graph area:

- **Hide test files** — filter nodes whose path matches `/(^|\/)(test|tests|__tests__|spec|specs)(\/|$)/` or whose filename ends in `.test.*` / `.spec.*`.
- **Hide infrastructure** — filters `is_outlier_hub` nodes.
- **Show only cycles** — dims non-cycle nodes to 15% opacity and hides their edges.
- **Renderer** dropdown — Auto / SVG / Canvas / Meta-graph (manual override).

All filters are client-side. Backend sends everything; frontend decides what to show.

---

## Verification tests

### Test A — SVG mode performance baseline
Analyze a 100-file repo. Chrome Performance tab for 10 seconds. Assert average FPS ≥50.

### Test B — SVG → Canvas auto-switch
Analyze an 800+ file repo. Confirm Canvas renderer is active (check DevTools element panel for `<canvas>` vs `<svg>`). Assert FPS ≥30 during panning.

### Test C — Meta-graph auto-activation
Analyze a 2000+ file repo (e.g., `https://github.com/nestjs/nest`). Confirm meta-graph renders with a reasonable number of meta-nodes (5–30), each labeled with path and file count.

### Test D — Meta expansion
Click a meta-node. Confirm it's replaced by its member files. Edges rebind correctly. Other meta-nodes remain intact.

### Test E — Meta collapse
With one cluster expanded, click its collapse button. Confirm it re-collapses to a single meta-node.

### Test F — Canvas hit-testing
In Canvas mode, hover over nodes at various zoom levels. Assert tooltip appears accurately, click-to-select works. No lag on hover.

### Test G — HiDPI rendering
On a Retina or 4K display, confirm canvas nodes/edges are sharp, not blurry. If blurry → `devicePixelRatio` setup is wrong.

### Test H — Outlier hub detection
Analyze a repo with a known hub file (e.g., a project with a huge shared `types.ts` imported everywhere). Confirm that file is pinned to a corner in gray.

### Test I — Filter combinations
Toggle "Hide tests" + "Show only cycles" on a repo with both cycles and tests. Confirm only non-test cycle nodes remain visible.

### Test J — Manual renderer override
Force SVG on a 1500-node graph via dropdown. Confirm it renders (slowly, as expected). Switch back to Auto. Confirm it reverts to Meta-graph.

---

## Out of scope for this phase
- AI explanations (Phase 8).
- Caching (Phase 9).
- Layout persistence across sessions.

---

## Common pitfalls
- **Without `devicePixelRatio` scaling, canvas is blurry on HiDPI.** Set `canvas.width = w * dpr; canvas.height = h * dpr;` then `ctx.scale(dpr, dpr)` before drawing.
- **Rebuilding quadtree every tick is expensive.** Every 5 ticks is fine for hit-testing.
- **`edge.source` starts as a string, becomes a node object after `forceLink.links()` is applied.** Always check type before dereferencing.
- **Line widths and dash patterns must divide by `transform.k`** to stay visually consistent under zoom.
- **Meta-graph mode: don't deduplicate A→B and B→A edges.** Keep them distinct — bidirectional dependencies between clusters are interesting.
- **Expanding all meta-nodes defeats the purpose.** Don't add an "expand all" button; force incremental exploration.
- **Transform state in React state causes re-renders per zoom pixel.** Keep it in a `useRef` and only trigger redraw via the simulation's tick or a manual `requestAnimationFrame`.
