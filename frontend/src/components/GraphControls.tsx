import { DEFAULT_FILTERS, FilterState } from "../graph/filters";

interface Props {
  filters: FilterState;
  onChange: (f: FilterState) => void;
  nodeCount: number;
  activeRenderer: string;
  darkMode?: boolean;
}

export function GraphControls({
  filters,
  onChange,
  nodeCount,
  activeRenderer,
  darkMode = false,
}: Props) {
  function toggle(key: keyof FilterState) {
    onChange({ ...filters, [key]: !filters[key] });
  }

  const bg = darkMode ? "#0d1117" : "#ffffff";
  const panelBg = darkMode ? "rgba(13, 17, 23, 0.95)" : "rgba(255, 255, 255, 0.95)";
  const border = darkMode ? "#30363d" : "#e5e7eb";
  const text = darkMode ? "#e6edf3" : "#111827";
  const textSubtle = darkMode ? "#8b949e" : "#6b7280";
  const inputBg = darkMode ? "#0d1117" : "#ffffff";
  const inputBorder = darkMode ? "#30363d" : "#d1d5db";
  const inputText = darkMode ? "#e6edf3" : "#111827";
  const btnHover = darkMode ? "#1c2128" : "#f3f4f6";

  return (
    <div
      style={{
        position: "absolute",
        top: 8,
        right: 8,
        zIndex: 10,
        background: panelBg,
        border: `1px solid ${border}`,
        borderRadius: 6,
        padding: "8px 10px",
        fontSize: 11,
        fontFamily: "monospace",
        display: "flex",
        flexDirection: "column",
        gap: 5,
        minWidth: 170,
        backdropFilter: "blur(10px)",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 2, color: text }}>
        Filters
      </div>

      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: text }}>
        <input
          type="checkbox"
          checked={filters.hideTests}
          onChange={() => toggle("hideTests")}
          style={{ accentColor: "#2563eb" }}
        />
        Hide test files
      </label>

      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: text }}>
        <input
          type="checkbox"
          checked={filters.hideInfrastructure}
          onChange={() => toggle("hideInfrastructure")}
          style={{ accentColor: "#2563eb" }}
        />
        Hide infrastructure
      </label>

      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: text }}>
        <input
          type="checkbox"
          checked={filters.onlyCycles}
          onChange={() => toggle("onlyCycles")}
          style={{ accentColor: "#2563eb" }}
        />
        Show only cycles
      </label>

      <div style={{ borderTop: `1px solid ${border}`, paddingTop: 5, marginTop: 2 }}>
        <div style={{ fontWeight: 600, marginBottom: 4, color: text }}>
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
            padding: "4px 6px",
            border: `1px solid ${inputBorder}`,
            borderRadius: 4,
            background: inputBg,
            color: inputText,
            cursor: "pointer",
          }}
        >
          <option value="auto">Auto</option>
          <option value="svg">SVG</option>
          <option value="canvas">Canvas</option>
          <option value="meta">Meta-graph</option>
        </select>
        <div style={{ marginTop: 4, color: textSubtle, fontSize: 10 }}>
          {nodeCount} nodes · {activeRenderer}
        </div>
      </div>

      <button
        onClick={() => onChange(DEFAULT_FILTERS)}
        style={{
          marginTop: 4,
          padding: "4px 8px",
          fontSize: 10,
          border: `1px solid ${inputBorder}`,
          borderRadius: 4,
          background: inputBg,
          color: textSubtle,
          cursor: "pointer",
          transition: "all 0.2s",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = btnHover;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = inputBg;
        }}
      >
        Reset
      </button>
    </div>
  );
}
