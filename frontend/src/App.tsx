import { useCallback, useEffect, useRef, useState } from "react";
import { GraphView } from "./components/GraphView";
import { NodeTooltip } from "./components/NodeTooltip";
import { ProgressBar } from "./components/ProgressBar";
import { Sidebar } from "./components/Sidebar";
import { DEFAULT_FILTERS, FilterState } from "./graph/filters";
import { Node } from "./graph/types";
import { useAnalysis } from "./hooks/useAnalysis";

const DEMO_REPOS = [
  { label: "psf/requests", url: "https://github.com/psf/requests" },
  { label: "fastapi/fastapi", url: "https://github.com/fastapi/fastapi" },
  { label: "tj/commander.js", url: "https://github.com/tj/commander.js" },
  { label: "axios/axios", url: "https://github.com/axios/axios" },
  { label: "pallets/flask", url: "https://github.com/pallets/flask" },
];

const ERROR_MAP: [string, string][] = [
  ["Rate limit", "Too many analyses — 5 per hour. Please wait before trying again."],
  ["Repository not found or private", "Repository not found. Make sure it's public and the URL is correct."],
  ["Repository is private", "This repository is private. Only public repos are supported."],
  ["exceeds 50 MB", "Repository is too large (>50 MB). Try a specific branch or a smaller repo."],
  ["exceeds 5000-file", "Repository has too many files (>5000). Try a smaller repo."],
  ["Stream connection lost", "Connection dropped. Please try again."],
  ["Clone failed", "Could not clone the repository. It may be private or temporarily unavailable."],
];

function friendlyError(raw: string): string {
  for (const [key, msg] of ERROR_MAP) {
    if (raw.includes(key)) return msg;
  }
  return raw;
}

export default function App() {
  const [url, setUrl] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<Node | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string> | null>(
    null,
  );
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [darkMode, setDarkMode] = useState(() => {
    try {
      return localStorage.getItem("depgraph-dark") === "1";
    } catch {
      return false;
    }
  });
  const [showColdStart, setShowColdStart] = useState(false);

  const API = import.meta.env.VITE_API_URL ?? "/api";
  const prewarmRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const coldStartRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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
    jobId,
  } = state;

  // Persist dark mode preference
  useEffect(() => {
    try {
      localStorage.setItem("depgraph-dark", darkMode ? "1" : "0");
    } catch {}
    document.documentElement.style.colorScheme = darkMode ? "dark" : "light";
  }, [darkMode]);

  // Read ?repo= from URL on mount and auto-submit
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const repoUrl = params.get("repo");
    if (repoUrl) {
      setUrl(repoUrl);
      analyze(repoUrl);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Keyboard shortcuts: Esc = deselect, / = focus input
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setSelectedNodeId(null);
        setHighlightedNodes(null);
      }
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Cold-start banner: visible after 3s of loading with no nodes yet
  useEffect(() => {
    if (coldStartRef.current) clearTimeout(coldStartRef.current);
    if (loading && nodes.length === 0) {
      coldStartRef.current = setTimeout(() => setShowColdStart(true), 3000);
    } else {
      setShowColdStart(false);
    }
    return () => {
      if (coldStartRef.current) clearTimeout(coldStartRef.current);
    };
  }, [loading, nodes.length]);

  const selectedNode = selectedNodeId
    ? (nodes.find((n) => n.id === selectedNodeId) ?? null)
    : null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSelectedNodeId(null);
    setHighlightedNodes(null);
    const params = new URLSearchParams();
    params.set("repo", url);
    history.replaceState(null, "", `?${params.toString()}`);
    await analyze(url);
  }

  function handleDemo(demoUrl: string) {
    setUrl(demoUrl);
    setSelectedNodeId(null);
    setHighlightedNodes(null);
    const params = new URLSearchParams();
    params.set("repo", demoUrl);
    history.replaceState(null, "", `?${params.toString()}`);
    analyze(demoUrl);
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

  // Theme tokens
  const bg = darkMode ? "#0d1117" : "#ffffff";
  const borderColor = darkMode ? "#30363d" : "#e5e7eb";
  const textColor = darkMode ? "#e6edf3" : "#111827";
  const subtleColor = darkMode ? "#8b949e" : "#6b7280";
  const chipBg = darkMode ? "#161b22" : "#f3f4f6";
  const chipBorder = darkMode ? "#30363d" : "#d1d5db";
  const btnBg = darkMode ? "#238636" : "#1a1a1a";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        fontFamily: "monospace",
        overflow: "hidden",
        background: bg,
        color: textColor,
      }}
    >
      {/* ── Header ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "8px 14px",
          borderBottom: `1px solid ${borderColor}`,
          background: bg,
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
            ref={inputRef}
            type="url"
            required
            placeholder="https://github.com/psf/requests"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              if (prewarmRef.current) clearTimeout(prewarmRef.current);
              const val = e.target.value;
              if (
                val.startsWith("https://github.com/") ||
                val.startsWith("https://gitlab.com/") ||
                val.startsWith("https://bitbucket.org/")
              ) {
                prewarmRef.current = setTimeout(() => {
                  fetch(`${API}/healthz`).catch(() => {});
                }, 500);
              }
            }}
            style={{
              flex: 1,
              padding: "5px 10px",
              fontSize: 13,
              border: `1px solid ${chipBorder}`,
              borderRadius: 4,
              outline: "none",
              background: bg,
              color: textColor,
            }}
          />
          <button
            type="submit"
            disabled={loading}
            style={{
              padding: "5px 16px",
              fontSize: 13,
              background: btnBg,
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

        {/* Dark mode toggle */}
        <button
          onClick={() => setDarkMode((d) => !d)}
          title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
          style={{
            padding: "4px 8px",
            fontSize: 14,
            background: "none",
            border: `1px solid ${chipBorder}`,
            borderRadius: 4,
            cursor: "pointer",
            color: textColor,
            flexShrink: 0,
            lineHeight: 1,
          }}
        >
          {darkMode ? "☀" : "☾"}
        </button>

        {stats && (
          <div
            style={{ fontSize: 11, color: subtleColor, whiteSpace: "nowrap" }}
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
            {friendlyError(error)}
          </div>
        )}
      </div>

      {/* ── Cold-start banner ── */}
      {showColdStart && loading && (
        <div
          style={{
            padding: "6px 14px",
            background: darkMode ? "#1c2128" : "#fffbeb",
            borderBottom: `1px solid ${darkMode ? "#f59e0b55" : "#fcd34d"}`,
            fontSize: 12,
            color: darkMode ? "#d29922" : "#92400e",
            flexShrink: 0,
          }}
        >
          Backend is waking up on Render free tier — this can take 30–60
          seconds on the first request. Hang tight...
        </div>
      )}

      {/* ── Body ── */}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <div
          style={{
            flex: 1,
            position: "relative",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <ProgressBar
            loading={loading}
            statusMsg={statusMsg}
            progress={progress}
          />

          {/* Landing empty state — only when nothing is happening */}
          {!loading && nodes.length === 0 && !error && (
            <div
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 24,
                padding: 32,
                color: subtleColor,
              }}
            >
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 48, marginBottom: 12, opacity: 0.6 }}>
                  ⬡
                </div>
                <div
                  style={{
                    fontSize: 16,
                    fontWeight: 600,
                    color: textColor,
                    marginBottom: 8,
                  }}
                >
                  Visualise any repository's dependency graph
                </div>
                <div style={{ fontSize: 13 }}>
                  Paste a GitHub, GitLab, or Bitbucket URL above, or try a
                  demo:
                </div>
              </div>

              {/* Demo chips */}
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 8,
                  justifyContent: "center",
                }}
              >
                {DEMO_REPOS.map((d) => (
                  <button
                    key={d.url}
                    onClick={() => handleDemo(d.url)}
                    style={{
                      padding: "6px 14px",
                      fontSize: 12,
                      background: chipBg,
                      border: `1px solid ${chipBorder}`,
                      borderRadius: 20,
                      cursor: "pointer",
                      color: textColor,
                      fontFamily: "monospace",
                    }}
                  >
                    {d.label}
                  </button>
                ))}
              </div>

              <div style={{ fontSize: 11, color: subtleColor }}>
                Tip: press{" "}
                <kbd
                  style={{
                    padding: "1px 5px",
                    border: `1px solid ${chipBorder}`,
                    borderRadius: 3,
                    background: chipBg,
                    fontSize: 11,
                  }}
                >
                  /
                </kbd>{" "}
                to focus the URL bar ·{" "}
                <kbd
                  style={{
                    padding: "1px 5px",
                    border: `1px solid ${chipBorder}`,
                    borderRadius: 3,
                    background: chipBg,
                    fontSize: 11,
                  }}
                >
                  Esc
                </kbd>{" "}
                to deselect
              </div>
            </div>
          )}

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
          jobId={jobId}
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
