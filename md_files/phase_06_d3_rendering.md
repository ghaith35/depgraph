# DepGraph — Phase 6: D3 Force-Directed Graph Rendering

## Goal
Replace the Phase 5 placeholder UI with an interactive, zoomable, force-directed graph. Nodes colored by language, sized by LOC. Edges rendered correctly (cycle edges red, dynamic edges dashed). Drag, pan, zoom, hover tooltip, click-to-select.

## Time budget
4 hours.

## Prerequisites
Phase 5 complete. SSE stream emits nodes/edges incrementally.

---

## Dependencies to add (frontend)
```
d3
@types/d3
```

---

## Component structure

```
frontend/src/
├── components/
│   ├── GraphCanvas.tsx        # SVG-based force-directed graph
│   ├── NodeTooltip.tsx        # Hover info overlay
│   ├── Sidebar.tsx            # Selected node details, setup steps, cycle list
│   ├── ProgressBar.tsx        # Analysis progress from SSE progress events
│   └── LanguageLegend.tsx     # Color key
├── graph/
│   ├── simulation.ts          # D3 force simulation setup
│   ├── colors.ts              # Language → color mapping
│   └── types.ts               # Node/Edge TypeScript types mirroring backend schema
├── hooks/
│   └── useAnalysis.ts         # EventSource hook from Phase 5
└── App.tsx
```

---

## Core principles

- **Simulation state lives in a `useRef`, not React state.** React re-rendering every tick destroys performance. The simulation mutates node x/y via closures; D3 draws directly to the DOM.
- **Nodes/edges arrays are mutated in place, not replaced.** D3's data join with a key function (`.data(nodes, d => d.id)`) handles incremental updates cleanly.
- **One `useEffect` creates the simulation (runs once). A second `useEffect` updates data when nodes/edges change.**

---

## Force simulation parameters (fixed, do not deviate)

```ts
const sim = d3.forceSimulation<Node>()
  .force("link", d3.forceLink<Node, Edge>()
    .id(d => d.id)
    .distance(60)
    .strength(0.7))
  .force("charge", d3.forceManyBody()
    .strength(-300 * (1 + Math.log10(Math.max(1, nodes.length) / 50))))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collide", d3.forceCollide()
    .radius(d => nodeRadius(d) + 4)
    .strength(0.9))
  .force("x", d3.forceX(width / 2).strength(0.05))
  .force("y", d3.forceY(height / 2).strength(0.05))
  .alphaDecay(0.04);
```

Justification for each:
- `forceLink.distance(60)` — short links because dependency edges are conceptually short-range.
- `forceLink.strength(0.7)` — strong enough to cluster related nodes, not so strong that long chains compress.
- `forceManyBody.strength(-300 * scale)` — log-scaled with node count so dense graphs don't collapse into a hairball.
- `forceCollide.strength(0.9)` — high strength prevents label overlap (the dominant readability problem).
- `forceX/forceY.strength(0.05)` — weak centering so dragged nodes can spread without the graph drifting off-screen.
- `alphaDecay(0.04)` — faster convergence than default `0.0228`; accept slightly suboptimal layout for perceived snappiness.

---

## Visual encoding

### Language colors (`graph/colors.ts`)
```ts
export const LANGUAGE_COLORS: Record<string, string> = {
  Python: "#3776AB",
  JavaScript: "#F7DF1E",
  TypeScript: "#3178C6",
  Java: "#E76F00",
  Go: "#00ADD8",
  Rust: "#CE422B",
  C: "#555555",
  "C++": "#00599C",
  Unknown: "#9CA3AF",
};

export function languageColor(lang: string): string {
  return LANGUAGE_COLORS[lang] ?? LANGUAGE_COLORS.Unknown;
}
```

### Node radius
```ts
export function nodeRadius(node: Node): number {
  const loc = Math.max(1, node.size);
  return Math.min(30, Math.max(8, 8 + Math.log10(loc + 1) * 4));
}
```

### Node styling
- Fill: `languageColor(d.language)`.
- Stroke: `#fff` default, `#e11d48` red if `is_cycle`, `#2563eb` blue if selected (selected overrides cycle).
- Stroke width: 1.5 default, 3 if cycle, 4 if selected.

### Edge styling
- Stroke: `#999` default, `#e11d48` if `is_cycle`.
- Width: 1 default, 2 if cycle.
- `stroke-dasharray: "4,4"` if `has_dynamic_target`.
- Arrow marker at end (use `<defs><marker>`).
- Opacity: 0.6 baseline, 1.0 when hovered.

---

## Streaming updates (critical)

Naive pattern: every SSE event triggers a React state update → every update re-renders → every render recreates the simulation. This kills performance at 50+ nodes.

**Correct pattern — buffer and batch:**

```tsx
const bufferRef = useRef<{ nodes: Node[], edges: Edge[] }>({ nodes: [], edges: [] });
const [nodes, setNodes] = useState<Node[]>([]);
const [edges, setEdges] = useState<Edge[]>([]);

// In the EventSource setup:
es.addEventListener("node", (e) => {
  bufferRef.current.nodes.push(JSON.parse(e.data));
});
es.addEventListener("edge", (e) => {
  bufferRef.current.edges.push(JSON.parse(e.data));
});

// Flush buffer every 100ms
useEffect(() => {
  const interval = setInterval(() => {
    if (bufferRef.current.nodes.length || bufferRef.current.edges.length) {
      setNodes(prev => [...prev, ...bufferRef.current.nodes]);
      setEdges(prev => [...prev, ...bufferRef.current.edges]);
      bufferRef.current = { nodes: [], edges: [] };
    }
  }, 100);
  return () => clearInterval(interval);
}, []);
```

When `nodes`/`edges` state updates, the D3 data-binding `useEffect` runs:

```tsx
useEffect(() => {
  const sim = simulationRef.current;
  if (!sim) return;

  sim.nodes(nodes);
  (sim.force("link") as d3.ForceLink<Node, Edge>).links(edges);
  sim.alpha(0.3).restart();  // gentle nudge, not full reheat

  // Data joins for circles and lines — enter/update/exit pattern
  // (see full code in GraphCanvas.tsx — key functions d => d.id for nodes,
  //  d => `${d.source}-${d.target}-${d.line}` for edges)
}, [nodes, edges, selectedNodeId]);
```

`sim.alpha(0.3)` — not 1.0 — prevents the whole graph from exploding every time a node arrives.

---

## Drag behavior

```ts
function dragBehavior(sim: d3.Simulation<Node, Edge>) {
  return d3.drag<SVGGElement, Node>()
    .on("start", (event, d) => {
      if (!event.active) sim.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    })
    .on("drag", (event, d) => {
      d.fx = event.x;
      d.fy = event.y;
    })
    .on("end", (event, d) => {
      if (!event.active) sim.alphaTarget(0);
      // Leave node pinned (fx/fy set) — user explicitly positioned it.
      // Add double-click handler elsewhere to unpin: d.fx = null; d.fy = null;
    });
}
```

---

## Zoom behavior

```ts
const zoom = d3.zoom<SVGSVGElement, unknown>()
  .scaleExtent([0.1, 8])
  .on("zoom", (event) => {
    g.attr("transform", event.transform);
  });
svg.call(zoom);
```

Scale extent `[0.1, 8]` — 0.1× zoom-out sees entire huge repos at once; 8× zoom-in reads tiny labels.

---

## Hover tooltip (NodeTooltip.tsx)

Absolutely-positioned div, rendered outside the SVG. Position updated on mouseenter/mousemove:

```tsx
<div
  ref={tooltipRef}
  style={{
    position: "fixed",
    pointerEvents: "none",
    background: "rgba(17, 24, 39, 0.95)",
    color: "white",
    padding: "8px 12px",
    borderRadius: "4px",
    fontSize: "12px",
    display: hoveredNode ? "block" : "none",
    left: mouseX + 15,
    top: mouseY + 15,
  }}
>
  {hoveredNode && (
    <>
      <div style={{ fontWeight: "bold" }}>{hoveredNode.id}</div>
      <div>{hoveredNode.language} · {hoveredNode.size} LOC</div>
      {hoveredNode.is_cycle && <div style={{ color: "#fca5a5" }}>In cycle</div>}
    </>
  )}
</div>
```

---

## Sidebar (Sidebar.tsx)

Three collapsible sections:

### 1. Selected file (when a node is selected)
- File path (rendered as clickable link to `https://github.com/{owner}/{repo}/blob/{commit_sha}/{path}`).
- Language, size (LOC).
- "Imports" list: all outgoing edges, each clickable to navigate selection.
- "Imported by" list: all incoming edges, each clickable.
- "Explain this file" button — disabled in Phase 6, wired up in Phase 8.

### 2. Setup instructions (always shown once `setup` event arrives)
- Runtime badge.
- Install command in a `<code>` block with a copy button.
- Build command, run command same treatment.
- Env vars as a bullet list.
- Notes section if non-empty.

### 3. Cycles (shown if any detected)
- Header with count: "3 circular dependencies detected".
- One card per SCC:
  - List of file IDs (each clickable to select and zoom).
  - "Highlight" button temporarily dims non-SCC nodes/edges.
  - Expandable simple-cycle paths: `a.py → b.py → c.py → a.py`.

---

## Progress bar (ProgressBar.tsx)

A thin horizontal bar at the top of the graph canvas, showing percent from `progress` SSE events. Labels the current stage underneath: "Cloning...", "Parsing 87/142 files...", "Resolving imports...". Disappears on `done` event.

---

## App layout

```
┌─────────────────────────────────────────────────────────────┐
│ [URL input] [Analyze]                       DepGraph        │
├──────────────────────────────────────┬──────────────────────┤
│                                      │                      │
│                                      │  Selected file       │
│        Graph canvas                  │  ─────────────       │
│        (SVG + D3)                    │  src/app/main.py     │
│                                      │  Python · 142 LOC    │
│                                      │                      │
│                                      │  Imports (3)         │
│                                      │  · utils.py          │
│                                      │  · models.py         │
│                                      │  · config.py         │
│                                      │                      │
│                                      │  Imported by (7)     │
│                                      │  · ...               │
│                                      │                      │
│                                      ├──────────────────────┤
│                                      │  Setup               │
│                                      │  Python              │
│                                      │  pip install -r ...  │
│                                      ├──────────────────────┤
│  [Legend]                            │  Cycles (2)          │
│  Python ● JavaScript ● ...           │  · {a, b, c}         │
└──────────────────────────────────────┴──────────────────────┘
```

Layout with CSS grid or flex. Canvas grows to fill available space. Sidebar fixed at ~360px wide, scrollable.

---

## Verification tests

### Test A — small repo renders
Analyze a ~30-file Python repo (`https://github.com/pallets/click`). Assert:
- All nodes appear within 3 seconds of connection.
- Layout converges within 10 seconds.
- Labels are readable, not catastrophically overlapping.

### Test B — colors match language
Analyze a polyglot repo. Open in browser, visually confirm Python blue, TS blue, JS yellow, Rust red-orange, etc.

### Test C — cycles visible
Analyze the Phase 4 `cycle_three` fixture. Assert all 3 nodes have red borders; all 3 edges between them are red.

### Test D — drag and pin
Drag a node. Release. Node stays where dropped. Simulation continues for other nodes.

### Test E — zoom and pan
Scroll to zoom, drag empty space to pan. Labels scale with the graph (not fixed pixel size).

### Test F — incremental streaming
Throttle network to "Slow 3G" in DevTools. Analyze a 100-file repo. Observe: nodes appear over ~10-15 seconds, force simulation rearranges continuously. No single "blank → everything-at-once" jump.

### Test G — click-to-select
Click a node. Sidebar populates. Click another. Sidebar updates.

### Test H — hover tooltip
Hover over a node. Tooltip appears with file path. Move cursor. Tooltip follows. Move off graph. Tooltip disappears.

### Test I — dynamic imports visible
Analyze a repo with template-string dynamic imports (e.g., i18n locale loading). Assert those edges render with dashed lines.

---

## Out of scope for this phase
- Canvas fallback for large graphs (Phase 7).
- Clustering / meta-graph mode (Phase 7).
- AI explanations (Phase 8).
- IndexedDB layout caching.

---

## Common pitfalls
- **Don't put the simulation in React state.** It causes a re-render per tick. Use `useRef`.
- **Don't recreate the simulation on every data change.** Create once in the first `useEffect`; update nodes/links in the second.
- **Don't forget the enter/update/exit pattern.** Missing `.exit().remove()` leaks DOM nodes.
- **Don't set `sim.alpha(1)` on each data update.** Use `0.3` — full reheat on every new node causes layout thrashing.
- **Don't use `forceCenter` without `forceX`/`forceY`.** The graph can drift off-screen during dragging.
- **Arrow markers need enough `refX`.** Set it so the arrowhead sits just outside the target node's circle, not overlapping.
- **Key functions are mandatory for `.data(nodes, d => d.id)`.** Without keys, D3 rebinds by index and nodes "teleport" between positions on updates.
- **`node.x` is undefined before the first tick.** Either initialize positions or check in the tick handler.
- **Stop the simulation on unmount.** Otherwise it runs forever in the background.
