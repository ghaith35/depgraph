import { DEFAULT_FILTERS, FilterState } from "../graph/filters";

interface Props {
  filters: FilterState;
  onChange: (f: FilterState) => void;
  nodeCount: number;
  activeRenderer: string;
}

export function GraphControls({
  filters,
  onChange,
  nodeCount,
  activeRenderer,
}: Props) {
  function toggle(key: keyof FilterState) {
    onChange({ ...filters, [key]: !filters[key] });
  }

  return (
    <div
      style={{
        position: "absolute",
        top: 8,
        right: 8,
        zIndex: 10,
        background: "rgba(255,255,255,0.95)",
        border: "1px solid #e5e7eb",
        borderRadius: 6,
        padding: "8px 10px",
        fontSize: 11,
        fontFamily: "monospace",
        display: "flex",
        flexDirection: "column",
        gap: 5,
        minWidth: 170,
      }}
    >
      <div
        style={{ fontWeight: 600, marginBottom: 2, color: "#374151" }}
      >
        Filters
      </div>

      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={filters.hideTests}
          onChange={() => toggle("hideTests")}
        />
        Hide test files
      </label>

      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={filters.hideInfrastructure}
          onChange={() => toggle("hideInfrastructure")}
        />
        Hide infrastructure
      </label>

      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={filters.onlyCycles}
          onChange={() => toggle("onlyCycles")}
        />
        Show only cycles
      </label>

      <div style={{ borderTop: "1px solid #e5e7eb", paddingTop: 5, marginTop: 2 }}>
        <div style={{ fontWeight: 600, marginBottom: 4, color: "#374151" }}>
          Renderer
        </div>
        <select
          value={filters.rendererOverride ?? "auto"}
          onChange={(e) =>
            onChange({
              ...filters,
              rendererOverride:
                e.target.value === "auto"
                  ? null
                  : (e.target.value as FilterState["rendererOverride"]),
            })
          }
          style={{
            width: "100%",
            fontSize: 11,
            padding: "2px 4px",
            border: "1px solid #d1d5db",
            borderRadius: 4,
          }}
        >
          <option value="auto">Auto</option>
          <option value="svg">SVG</option>
          <option value="canvas">Canvas</option>
          <option value="meta">Meta-graph</option>
        </select>
        <div style={{ marginTop: 4, color: "#9ca3af" }}>
          {nodeCount} nodes · {activeRenderer}
        </div>
      </div>

      <button
        onClick={() => onChange(DEFAULT_FILTERS)}
        style={{
          marginTop: 2,
          padding: "2px 6px",
          fontSize: 10,
          border: "1px solid #e5e7eb",
          borderRadius: 4,
          background: "white",
          cursor: "pointer",
          color: "#6b7280",
        }}
      >
        Reset
      </button>
    </div>
  );
}
