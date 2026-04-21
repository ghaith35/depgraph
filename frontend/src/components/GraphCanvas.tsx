import * as d3 from "d3";
import { useEffect, useRef } from "react";
import { buildClusterCentroids, makeClusterForce } from "../graph/clustering";
import { languageColor, nodeRadius } from "../graph/colors";
import { createSimulation, updateChargeStrength } from "../graph/simulation";
import { Edge, Node } from "../graph/types";

interface Props {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  highlightedNodes: Set<string> | null;
  onSelectNode: (id: string | null) => void;
  onHoverNode: (node: Node | null, x: number, y: number) => void;
}

export function GraphCanvas({
  nodes,
  edges,
  selectedNodeId,
  highlightedNodes,
  onSelectNode,
  onHoverNode,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<d3.Selection<
    SVGGElement,
    unknown,
    null,
    undefined
  > | null>(null);
  const simRef = useRef<d3.Simulation<Node, Edge> | null>(null);

  // Always-fresh callback refs — avoids stale closures in the init effect
  const onSelectRef = useRef(onSelectNode);
  const onHoverRef = useRef(onHoverNode);
  useEffect(() => {
    onSelectRef.current = onSelectNode;
  });
  useEffect(() => {
    onHoverRef.current = onHoverNode;
  });

  // ── Effect 1: create SVG scaffold + simulation (runs once) ──────────────
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;

    const width = el.clientWidth || 800;
    const height = el.clientHeight || 600;
    const svg = d3.select(el);

    // Arrow markers
    const defs = svg.append("defs");
    (
      [
        ["arrow", "#999"],
        ["arrow-cycle", "#e11d48"],
      ] as const
    ).forEach(([id, fill]) => {
      defs
        .append("marker")
        .attr("id", id)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 10) // tip of path lands at endpoint (node boundary)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("fill", fill);
    });

    const g = svg.append("g");
    gRef.current = g;
    g.append("g").attr("class", "edges");
    g.append("g").attr("class", "nodes");

    // Zoom / pan
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 8])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom);

    // Click on background deselects
    svg.on("click", (event) => {
      if (event.target === el) onSelectRef.current(null);
    });

    // Simulation
    const sim = createSimulation(width, height);

    sim.on("tick", () => {
      const g = gRef.current;
      if (!g) return;

      // Edges: x1/y1 at source center; x2/y2 at target circle boundary
      g.select<SVGGElement>(".edges")
        .selectAll<SVGLineElement, Edge>("line")
        .attr("x1", (d) => (d.source as Node).x ?? 0)
        .attr("y1", (d) => (d.source as Node).y ?? 0)
        .attr("x2", (d) => {
          const s = d.source as Node;
          const t = d.target as Node;
          const dx = (t.x ?? 0) - (s.x ?? 0);
          const dy = (t.y ?? 0) - (s.y ?? 0);
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          return (t.x ?? 0) - (dx / dist) * nodeRadius(t);
        })
        .attr("y2", (d) => {
          const s = d.source as Node;
          const t = d.target as Node;
          const dx = (t.x ?? 0) - (s.x ?? 0);
          const dy = (t.y ?? 0) - (s.y ?? 0);
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          return (t.y ?? 0) - (dy / dist) * nodeRadius(t);
        });

      // Nodes: translate group to current position
      g.select<SVGGElement>(".nodes")
        .selectAll<SVGGElement, Node>("g.node-group")
        .attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    simRef.current = sim;

    return () => {
      sim.stop();
      svg.selectAll("*").remove();
      simRef.current = null;
      gRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Effect 2: update D3 data bindings when nodes/edges change ───────────
  useEffect(() => {
    const sim = simRef.current;
    const g = gRef.current;
    if (!sim || !g) return;

    updateChargeStrength(sim, nodes.length);

    // Add cluster force for 300+ nodes; reduce charge to avoid double repulsion
    if (nodes.length >= 300) {
      const w = svgRef.current?.clientWidth || 800;
      const h = svgRef.current?.clientHeight || 600;
      const centroids = buildClusterCentroids(nodes, w, h);
      sim.force("cluster", makeClusterForce(centroids, 0.15));
      (sim.force("charge") as d3.ForceManyBody<Node>).strength(-150);
    } else {
      sim.force("cluster", null);
    }

    const drag = d3
      .drag<SVGGElement, Node>()
      .on("start", (event, d) => {
        if (!event.active) sim.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event) => {
        if (!event.active) sim.alphaTarget(0);
        // Leave node pinned — user double-clicks to unpin
      });

    // ── Edge join ────────────────────────────────────────────────────────
    const edgeSel = g
      .select<SVGGElement>(".edges")
      .selectAll<SVGLineElement, Edge>("line")
      .data(edges, (d) => {
        const s =
          typeof d.source === "string" ? d.source : (d.source as Node).id;
        const t =
          typeof d.target === "string" ? d.target : (d.target as Node).id;
        return `${s}→${t}:${d.line}`;
      });

    edgeSel.exit().remove();

    edgeSel
      .enter()
      .append("line")
      .attr("stroke", (d) => (d.is_cycle ? "#e11d48" : "#999"))
      .attr("stroke-width", (d) => (d.is_cycle ? 2 : 1))
      .attr("stroke-dasharray", (d) =>
        d.has_dynamic_target ? "4,4" : null,
      )
      .attr("stroke-opacity", 0.6)
      .attr("marker-end", (d) =>
        d.is_cycle ? "url(#arrow-cycle)" : "url(#arrow)",
      )
      .on("mouseenter", function () {
        d3.select(this).attr("stroke-opacity", 1);
      })
      .on("mouseleave", function () {
        d3.select(this).attr("stroke-opacity", 0.6);
      });

    // ── Node join ─────────────────────────────────────────────────────────
    const nodeSel = g
      .select<SVGGElement>(".nodes")
      .selectAll<SVGGElement, Node>("g.node-group")
      .data(nodes, (d) => d.id);

    nodeSel.exit().remove();

    const entered = nodeSel
      .enter()
      .append("g")
      .attr("class", "node-group")
      .attr("cursor", "pointer")
      .call(drag as never)
      .on("click", (event, d) => {
        event.stopPropagation();
        onSelectRef.current(d.id);
      })
      .on("mouseenter", (event, d) => {
        onHoverRef.current(d, event.clientX, event.clientY);
      })
      .on("mousemove", (event, d) => {
        onHoverRef.current(d, event.clientX, event.clientY);
      })
      .on("mouseleave", () => {
        onHoverRef.current(null, 0, 0);
      })
      .on("dblclick", (_, d) => {
        d.fx = null;
        d.fy = null;
        sim.alpha(0.1).restart();
      });

    entered.append("circle");
    entered
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => nodeRadius(d) + 12)
      .style("font-size", "9px")
      .style("font-family", "monospace")
      .style("fill", "#374151")
      .style("pointer-events", "none")
      .style("user-select", "none")
      .text((d) => d.label);

    // r + fill for all nodes (enter + existing); stroke handled by Effect 3
    const allNodes = g.select<SVGGElement>(".nodes")
      .selectAll<SVGGElement, Node>("g.node-group");

    allNodes
      .select("circle")
      .attr("r", (d) => nodeRadius(d))
      .attr("fill", (d) => languageColor(d.language))
      .attr("stroke", "#fff")
      .attr("stroke-width", 1.5);

    // Hide labels for dense graphs (tooltip handles hover info)
    allNodes
      .select("text")
      .style("display", nodes.length > 300 ? "none" : "block");

    // Feed updated arrays to simulation — gentle nudge (not full reheat)
    sim.nodes(nodes);
    (sim.force("link") as d3.ForceLink<Node, Edge>).links(edges);
    sim.alpha(0.3).restart();
  }, [nodes, edges]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Effect 3: visual state (selection + highlight) — no sim restart ────
  useEffect(() => {
    const g = gRef.current;
    if (!g) return;

    g.select<SVGGElement>(".nodes")
      .selectAll<SVGGElement, Node>("g.node-group")
      .attr("opacity", (d) =>
        highlightedNodes && !highlightedNodes.has(d.id) ? 0.08 : 1,
      )
      .select("circle")
      .attr("stroke", (d) => {
        if (d.id === selectedNodeId) return "#2563eb";
        if (d.is_cycle) return "#e11d48";
        return "#fff";
      })
      .attr("stroke-width", (d) => {
        if (d.id === selectedNodeId) return 4;
        if (d.is_cycle) return 3;
        return 1.5;
      });

    g.select<SVGGElement>(".edges")
      .selectAll<SVGLineElement, Edge>("line")
      .attr("opacity", (d) => {
        if (!highlightedNodes) return 1;
        const s =
          typeof d.source === "string" ? d.source : (d.source as Node).id;
        const t =
          typeof d.target === "string" ? d.target : (d.target as Node).id;
        return highlightedNodes.has(s) && highlightedNodes.has(t) ? 1 : 0.04;
      });
  }, [selectedNodeId, highlightedNodes]);

  return (
    <svg
      ref={svgRef}
      style={{ width: "100%", height: "100%", display: "block" }}
    />
  );
}
