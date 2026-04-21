import { useCallback, useState } from "react";
import { GraphView } from "./components/GraphView";
import { NodeTooltip } from "./components/NodeTooltip";
import { ProgressBar } from "./components/ProgressBar";
import { Sidebar } from "./components/Sidebar";
import { DEFAULT_FILTERS, FilterState } from "./graph/filters";
import { Node } from "./graph/types";
import { useAnalysis } from "./hooks/useAnalysis";

export default function App() {
  const [url, setUrl] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<Node | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string> | null>(
    null,
  );
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);

  const { state, analyze } = useAnalysis();
  const {
    loading,
    error,
    statusMsg,
    progress,
    nodes,
    edges,
    cycles,
    setup,
    stats,
  } = state;

  const selectedNode = selectedNodeId
    ? (nodes.find((n) => n.id === selectedNodeId) ?? null)
    : null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSelectedNodeId(null);
    setHighlightedNodes(null);
    await analyze(url);
  }

  const handleHoverNode = useCallback(
    (node: Node | null, x: number, y: number) => {
      setHoveredNode(node);
      if (node) setMousePos({ x, y });
    },
    [],
  );

  const handleHighlightCycle = useCallback((ids: string[] | null) => {
    setHighlightedNodes(ids ? new Set(ids) : null);
  }, []);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        fontFamily: "monospace",
        overflow: "hidden",
      }}
    >
      {/* ── Header ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "8px 14px",
          borderBottom: "1px solid #e5e7eb",
          background: "white",
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 17, flexShrink: 0 }}>
          DepGraph
        </span>

        <form
          onSubmit={handleSubmit}
          style={{ display: "flex", gap: 8, flex: 1 }}
        >
          <input
            type="url"
            required
            placeholder="https://github.com/psf/requests"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            style={{
              flex: 1,
              padding: "5px 10px",
              fontSize: 13,
              border: "1px solid #d1d5db",
              borderRadius: 4,
              outline: "none",
            }}
          />
          <button
            type="submit"
            disabled={loading}
            style={{
              padding: "5px 16px",
              fontSize: 13,
              background: "#1a1a1a",
              color: "#fff",
              border: "none",
              borderRadius: 4,
              cursor: loading ? "not-allowed" : "pointer",
              opacity: loading ? 0.7 : 1,
              flexShrink: 0,
            }}
          >
            {loading ? "Analysing…" : "Analyse"}
          </button>
        </form>

        {stats && (
          <div
            style={{ fontSize: 11, color: "#6b7280", whiteSpace: "nowrap" }}
          >
            {stats.file_count} files · {nodes.length} nodes · {edges.length}{" "}
            edges · {stats.analysis_duration_ms}ms
          </div>
        )}

        {error && (
          <div
            style={{
              fontSize: 12,
              color: "#dc2626",
              maxWidth: 300,
              wordBreak: "break-word",
            }}
          >
            {error}
          </div>
        )}
      </div>

      {/* ── Body ── */}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* Canvas area with progress bar overlay */}
        <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
          <ProgressBar
            loading={loading}
            statusMsg={statusMsg}
            progress={progress}
          />

          <GraphView
            nodes={nodes}
            edges={edges}
            filters={filters}
            onFiltersChange={setFilters}
            selectedNodeId={selectedNodeId}
            highlightedNodes={highlightedNodes}
            onSelectNode={setSelectedNodeId}
            onHoverNode={handleHoverNode}
          />
        </div>

        {/* Sidebar */}
        <Sidebar
          selectedNode={selectedNode}
          nodes={nodes}
          edges={edges}
          cycles={cycles}
          setup={setup}
          stats={stats}
          onSelectNode={setSelectedNodeId}
          onHighlightCycle={handleHighlightCycle}
        />
      </div>

      {/* Tooltip rendered outside everything so it's never clipped */}
      <NodeTooltip node={hoveredNode} x={mousePos.x} y={mousePos.y} />
    </div>
  );
}
