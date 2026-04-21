import { useState } from "react";
import { buildDisplayGraph, buildMetaGraph, MetaNode } from "../graph/metaGraph";
import { Edge, Node } from "../graph/types";
import { CanvasGraphCanvas } from "./CanvasGraphCanvas";

interface Props {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  highlightedNodes: Set<string> | null;
  onSelectNode: (id: string | null) => void;
  onHoverNode: (node: Node | null, x: number, y: number) => void;
}

export function MetaGraph({
  nodes,
  edges,
  selectedNodeId,
  highlightedNodes,
  onSelectNode,
  onHoverNode,
}: Props) {
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(
    new Set(),
  );

  const { metaNodes, metaEdges } = buildMetaGraph(nodes, edges);

  const { displayNodes, displayEdges } = buildDisplayGraph(
    nodes,
    edges,
    metaNodes,
    expandedClusters,
  );

  function handleDoubleClick(node: Node) {
    const mn = node as MetaNode;
    if (mn.kind === "meta") {
      // Expand this cluster
      setExpandedClusters((prev) => {
        const next = new Set(prev);
        next.add(mn.cluster);
        return next;
      });
      onSelectNode(null);
    } else {
      // Collapse the cluster this file belongs to
      const cluster = node.cluster || "(root)";
      setExpandedClusters((prev) => {
        const next = new Set(prev);
        next.delete(cluster);
        return next;
      });
      onSelectNode(null);
    }
  }

  // When selectedNode is in an expanded cluster, the parent can show a
  // "Collapse cluster" affordance. We surface this via a custom node field.
  // Inject a collapse hint on nodes from expanded clusters.
  const nodesWithHint = displayNodes.map((n) => {
    if (expandedClusters.has(n.cluster || "(root)")) {
      return { ...n, _canCollapse: true };
    }
    return n;
  });

  // Expose collapse function to App via meta info on selected node (handled in Sidebar)
  const handleSelectNode = (id: string | null) => {
    onSelectNode(id);
  };

  return (
    <>
      {/* Collapse hint badge — top-left corner */}
      {expandedClusters.size > 0 && (
        <div
          style={{
            position: "absolute",
            top: 8,
            left: 8,
            zIndex: 10,
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
            maxWidth: 300,
          }}
        >
          {[...expandedClusters].map((cluster) => (
            <button
              key={cluster}
              onClick={() => {
                setExpandedClusters((prev) => {
                  const next = new Set(prev);
                  next.delete(cluster);
                  return next;
                });
              }}
              style={{
                padding: "2px 8px",
                fontSize: 11,
                fontFamily: "monospace",
                background: "#1f2937",
                color: "white",
                border: "none",
                borderRadius: 4,
                cursor: "pointer",
              }}
              title="Collapse cluster"
            >
              × {cluster.split("/").pop() ?? cluster}
            </button>
          ))}
        </div>
      )}

      <CanvasGraphCanvas
        nodes={nodesWithHint as Node[]}
        edges={displayEdges}
        selectedNodeId={selectedNodeId}
        highlightedNodes={highlightedNodes}
        onSelectNode={handleSelectNode}
        onHoverNode={onHoverNode}
        onDoubleClickNode={handleDoubleClick}
      />

      {/* Double-click hint */}
      <div
        style={{
          position: "absolute",
          bottom: 44,
          left: 12,
          fontSize: 10,
          color: "#9ca3af",
          fontFamily: "monospace",
          pointerEvents: "none",
        }}
      >
        dbl-click cluster node to expand · dbl-click file node to collapse
      </div>
    </>
  );
}
