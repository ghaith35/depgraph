import { Node } from "../graph/types";

interface Props {
  node: Node | null;
  x: number;
  y: number;
}

export function NodeTooltip({ node, x, y }: Props) {
  if (!node) return null;

  return (
    <div
      style={{
        position: "fixed",
        left: x + 15,
        top: y + 15,
        pointerEvents: "none",
        background: "rgba(17, 24, 39, 0.95)",
        color: "white",
        padding: "8px 12px",
        borderRadius: 4,
        fontSize: 12,
        fontFamily: "monospace",
        zIndex: 1000,
        maxWidth: 320,
        wordBreak: "break-all",
      }}
    >
      <div style={{ fontWeight: "bold", marginBottom: 2 }}>{node.id}</div>
      <div style={{ color: "#d1d5db" }}>
        {node.language} · {node.size} LOC
      </div>
      {node.is_cycle && (
        <div style={{ color: "#fca5a5", marginTop: 2 }}>⚠ In cycle</div>
      )}
      {node.parse_error && (
        <div style={{ color: "#fca5a5", marginTop: 2 }}>Parse error</div>
      )}
    </div>
  );
}
