import { useMemo } from "react";
import { markOutlierHubs, applyFilters, FilterState } from "../graph/filters";
import { Edge, Node } from "../graph/types";
import { CanvasGraphCanvas } from "./CanvasGraphCanvas";
import { GraphCanvas } from "./GraphCanvas";
import { GraphControls } from "./GraphControls";
import { LanguageLegend } from "./LanguageLegend";
import { MetaGraph } from "./MetaGraph";

interface Props {
  nodes: Node[];
  edges: Edge[];
  filters: FilterState;
  onFiltersChange: (f: FilterState) => void;
  selectedNodeId: string | null;
  highlightedNodes: Set<string> | null;
  onSelectNode: (id: string | null) => void;
  onHoverNode: (node: Node | null, x: number, y: number) => void;
}

export function GraphView({
  nodes,
  edges,
  filters,
  onFiltersChange,
  selectedNodeId,
  highlightedNodes,
  onSelectNode,
  onHoverNode,
}: Props) {
  // Mark outlier hubs (mutates node objects — stable across renders)
  useMemo(() => {
    if (nodes.length > 0 && edges.length > 0) {
      markOutlierHubs(nodes, edges);
    }
  }, [nodes, edges]);

  // Apply filters
  const { nodes: filteredNodes, edges: filteredEdges } = useMemo(
    () => applyFilters(nodes, edges, filters),
    [nodes, edges, filters],
  );

  // Determine renderer
  const n = filteredNodes.length;
  const autoRenderer =
    n >= 1500 ? "meta" : n >= 800 ? "canvas" : "svg";
  const activeRenderer = filters.rendererOverride ?? autoRenderer;

  const sharedProps = {
    nodes: filteredNodes,
    edges: filteredEdges,
    selectedNodeId,
    highlightedNodes,
    onSelectNode,
    onHoverNode,
  };

  return (
    <div style={{ flex: 1, minHeight: 0, position: "relative", overflow: "hidden" }}>
      {activeRenderer === "meta" ? (
        <MetaGraph {...sharedProps} />
      ) : activeRenderer === "canvas" ? (
        <CanvasGraphCanvas {...sharedProps} />
      ) : (
        <GraphCanvas {...sharedProps} />
      )}

      {/* Legend */}
      {filteredNodes.length > 0 && (
        <div style={{ position: "absolute", bottom: 12, left: 12, zIndex: 5 }}>
          <LanguageLegend nodes={filteredNodes} />
        </div>
      )}

      {/* Controls */}
      <GraphControls
        filters={filters}
        onChange={onFiltersChange}
        nodeCount={filteredNodes.length}
        activeRenderer={activeRenderer}
      />
    </div>
  );
}
