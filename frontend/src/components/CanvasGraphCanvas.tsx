import * as d3 from "d3";
import { useEffect, useRef } from "react";
import { languageColor, nodeRadius } from "../graph/colors";
import { buildClusterCentroids, makeClusterForce } from "../graph/clustering";
import { createSimulation, updateChargeStrength } from "../graph/simulation";
import { Edge, Node } from "../graph/types";

interface Props {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  highlightedNodes: Set<string> | null;
  onSelectNode: (id: string | null) => void;
  onHoverNode: (node: Node | null, x: number, y: number) => void;
  /** Called when user double-clicks a node (e.g. to expand a meta-cluster). */
  onDoubleClickNode?: (node: Node) => void;
}

function eid(n: string | Node): string {
  return typeof n === "string" ? n : n.id;
}

export function CanvasGraphCanvas({
  nodes,
  edges,
  selectedNodeId,
  highlightedNodes,
  onSelectNode,
  onHoverNode,
  onDoubleClickNode,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const simRef = useRef<d3.Simulation<Node, Edge> | null>(null);
  const qtRef = useRef<d3.Quadtree<Node> | null>(null);
  const transformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);
  const hoveredRef = useRef<Node | null>(null);
  const drawRef = useRef<(() => void) | null>(null);

  // Always-fresh callback refs
  const onSelectRef = useRef(onSelectNode);
  const onHoverRef = useRef(onHoverNode);
  const onDblRef = useRef(onDoubleClickNode);
  useEffect(() => { onSelectRef.current = onSelectNode; });
  useEffect(() => { onHoverRef.current = onHoverNode; });
  useEffect(() => { onDblRef.current = onDoubleClickNode; });

  // State refs read by draw() without causing rerenders
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const selRef = useRef(selectedNodeId);
  const hlRef = useRef(highlightedNodes);
  useEffect(() => { nodesRef.current = nodes; edgesRef.current = edges; });
  useEffect(() => { selRef.current = selectedNodeId; hlRef.current = highlightedNodes; });

  // ── Effect 1: init canvas, simulation, event listeners (runs once) ──────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const container = canvas.parentElement!;
    const w = container.clientWidth || 800;
    const h = container.clientHeight || 600;
    const dpr = window.devicePixelRatio || 1;

    // HiDPI setup
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr); // now 1 ctx unit = 1 CSS pixel

    // ── Draw function ──────────────────────────────────────────────────────
    let rafId: number | null = null;

    function draw() {
      const ns = nodesRef.current;
      const es = edgesRef.current;
      const t = transformRef.current;
      const hovered = hoveredRef.current;
      const selId = selRef.current;
      const hl = hlRef.current;

      ctx.save();
      ctx.clearRect(0, 0, w, h);
      ctx.translate(t.x, t.y);
      ctx.scale(t.k, t.k);

      // Skip edges at very small zoom (too small to distinguish)
      if (t.k >= 0.25) {
        for (const e of es) {
          const s = e.source as Node;
          const tt = e.target as Node;
          if (s.x == null || tt.x == null) continue;

          const sid = eid(e.source);
          const tid = eid(e.target);
          const dimmed = hl && (!hl.has(sid) || !hl.has(tid));
          ctx.globalAlpha = dimmed ? 0.04 : 0.6;
          ctx.strokeStyle = e.is_cycle ? "#e11d48" : "#999";
          ctx.lineWidth = (e.is_cycle ? 2 : 1) / t.k;
          ctx.setLineDash(
            e.has_dynamic_target ? [4 / t.k, 4 / t.k] : [],
          );
          ctx.beginPath();
          ctx.moveTo(s.x!, s.y!);
          ctx.lineTo(tt.x!, tt.y!);
          ctx.stroke();
        }
        ctx.setLineDash([]);
      }

      ctx.globalAlpha = 1;

      for (const n of ns) {
        if (n.x == null) continue;
        const r = nodeRadius(n);
        const dimmed = hl && !hl.has(n.id);
        ctx.globalAlpha = dimmed ? 0.08 : 1;
        ctx.fillStyle = n.is_outlier_hub ? "#9ca3af" : languageColor(n.language);
        ctx.strokeStyle =
          n.id === selId
            ? "#2563eb"
            : n === hovered
            ? "#1f2937"
            : n.is_cycle
            ? "#e11d48"
            : "#fff";
        ctx.lineWidth =
          (n.id === selId ? 4 : n.is_cycle ? 3 : 1.5) / t.k;
        ctx.beginPath();
        ctx.arc(n.x, n.y!, r, 0, 2 * Math.PI);
        ctx.fill();
        ctx.stroke();

        // File-count badge for meta-nodes
        const mn = n as { file_count?: number };
        if (mn.file_count && t.k > 0.4) {
          ctx.globalAlpha = dimmed ? 0.08 : 1;
          ctx.fillStyle = "#1f2937";
          ctx.font = `bold ${Math.max(8, 9 / t.k)}px sans-serif`;
          ctx.textAlign = "center";
          ctx.fillText(String(mn.file_count), n.x!, n.y! + r * 0.4);
        }
      }
      ctx.globalAlpha = 1;

      // Label only for hovered node
      if (hovered && hovered.x != null) {
        const r = nodeRadius(hovered);
        ctx.fillStyle = "#1f2937";
        ctx.font = `${Math.max(9, 11 / t.k)}px monospace`;
        ctx.textAlign = "center";
        ctx.fillText(
          hovered.label,
          hovered.x,
          hovered.y! + r + 14 / t.k,
        );
      }

      ctx.restore();
    }

    drawRef.current = draw;

    function scheduleDraw() {
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        draw();
      });
    }

    // ── Simulation ─────────────────────────────────────────────────────────
    let tickCount = 0;
    const sim = createSimulation(w, h);

    sim.on("tick", () => {
      tickCount++;
      if (tickCount % 5 === 0) {
        qtRef.current = d3
          .quadtree<Node>()
          .x((n) => n.x ?? 0)
          .y((n) => n.y ?? 0)
          .addAll(nodesRef.current);
      }
      draw();
    });

    simRef.current = sim;

    // ── Zoom ───────────────────────────────────────────────────────────────
    const zoom = d3
      .zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.05, 8])
      .on("zoom", (event) => {
        transformRef.current = event.transform;
        scheduleDraw();
      });
    d3.select(canvas).call(zoom);

    // ── Mouse events ───────────────────────────────────────────────────────
    let lastClickTime = 0;
    let lastClickNode: Node | null = null;

    function worldPos(event: MouseEvent) {
      const rect = (canvas as HTMLCanvasElement).getBoundingClientRect();
      const t = transformRef.current;
      return {
        x: (event.clientX - rect.left - t.x) / t.k,
        y: (event.clientY - rect.top - t.y) / t.k,
      };
    }

    function hitTest(event: MouseEvent): Node | null {
      const { x, y } = worldPos(event);
      return qtRef.current?.find(x, y, 30) ?? null;
    }

    function onMouseMove(event: MouseEvent) {
      const found = hitTest(event);
      const prev = hoveredRef.current;
      hoveredRef.current = found;
      if (found !== prev) {
        onHoverRef.current(found, event.clientX, event.clientY);
        scheduleDraw();
      } else if (found) {
        // Update tooltip position even if same node
        onHoverRef.current(found, event.clientX, event.clientY);
      }
    }

    function onClick(event: MouseEvent) {
      const found = hitTest(event);
      const now = Date.now();
      // Detect double-click (within 300ms on same node)
      if (
        found &&
        found === lastClickNode &&
        now - lastClickTime < 300
      ) {
        onDblRef.current?.(found);
        lastClickNode = null;
        return;
      }
      lastClickNode = found;
      lastClickTime = now;
      onSelectRef.current(found ? found.id : null);
    }

    function onMouseLeave() {
      hoveredRef.current = null;
      onHoverRef.current(null, 0, 0);
      scheduleDraw();
    }

    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("click", onClick);
    canvas.addEventListener("mouseleave", onMouseLeave);

    return () => {
      sim.stop();
      if (rafId !== null) cancelAnimationFrame(rafId);
      canvas.removeEventListener("mousemove", onMouseMove);
      canvas.removeEventListener("click", onClick);
      canvas.removeEventListener("mouseleave", onMouseLeave);
      simRef.current = null;
      qtRef.current = null;
      drawRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Effect 2: update simulation data ────────────────────────────────────
  useEffect(() => {
    const sim = simRef.current;
    if (!sim) return;

    updateChargeStrength(sim, nodes.length);

    // Add cluster force for 300+ nodes
    if (nodes.length >= 300) {
      const canvas = canvasRef.current;
      const w = canvas?.clientWidth || 800;
      const h = canvas?.clientHeight || 600;
      const centroids = buildClusterCentroids(nodes, w, h);
      sim.force("cluster", makeClusterForce(centroids, 0.15));
      // Reduce charge when cluster force is active
      (sim.force("charge") as d3.ForceManyBody<Node>).strength(-150);
    } else {
      sim.force("cluster", null);
    }

    sim.nodes(nodes);
    (sim.force("link") as d3.ForceLink<Node, Edge>).links(edges);
    sim.alpha(0.3).restart();
  }, [nodes, edges]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Effect 3: redraw on visual state change (no sim restart) ────────────
  useEffect(() => {
    drawRef.current?.();
  }, [selectedNodeId, highlightedNodes]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: "100%", height: "100%", display: "block" }}
    />
  );
}
