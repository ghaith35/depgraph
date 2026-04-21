import { useState } from "react";

const API = import.meta.env.VITE_API_URL ?? "/api";

interface Edge {
  source: string;
  target: string;
  symbol: string | null;
  line: number;
  is_cycle: boolean;
}

interface Node {
  id: string;
  label: string;
  language: string;
  size: number;
  is_cycle: boolean;
  cluster: string;
}

interface AnalysisResult {
  job_id: string;
  schema_version: string;
  stats: {
    file_count: number;
    total_size_bytes: number;
    commit_sha: string;
    languages: Record<string, number>;
    analysis_duration_ms: number;
  };
  graph: {
    nodes: Node[];
    edges: Edge[];
  };
  cycles: {
    scc_count: number;
    node_count_in_cycles: number;
    sccs: string[][];
  };
  setup: {
    runtime: string;
    install_cmd: string | null;
    build_cmd: string | null;
    run_cmd: string | null;
    env_vars: string[];
    notes: string[];
  };
}

const badge = (text: string, color: string) => (
  <span style={{ background: color, borderRadius: 4, padding: "2px 8px", fontSize: 12, marginRight: 4 }}>
    {text}
  </span>
);

export default function App() {
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
      console.log("analyze result:", data);
      setResult(data);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ fontFamily: "monospace", maxWidth: 700, margin: "60px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 28, marginBottom: 4 }}>DepGraph</h1>
      <p style={{ color: "#666", marginBottom: 24, fontSize: 14 }}>
        Paste a GitHub / GitLab / Bitbucket URL to analyse its dependency graph.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        <input
          type="url"
          required
          placeholder="https://github.com/psf/requests"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          style={{ flex: 1, padding: "8px 12px", fontSize: 14, border: "1px solid #ccc", borderRadius: 4 }}
        />
        <button
          type="submit"
          disabled={loading}
          style={{ padding: "8px 20px", fontSize: 14, background: "#1a1a1a", color: "#fff", border: "none", borderRadius: 4, cursor: loading ? "not-allowed" : "pointer" }}
        >
          {loading ? "Analysing…" : "Analyse"}
        </button>
      </form>

      {loading && <p style={{ color: "#666", fontSize: 13 }}>Cloning repo, this takes a few seconds…</p>}
      {error && <p style={{ color: "#dc2626", fontSize: 13 }}>Error: {error}</p>}

      {result && (
        <div style={{ fontSize: 13 }}>

          {/* Stats row */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
            {badge(`${result.graph.nodes.length} files`, "#e5e5e5")}
            {badge(`${result.graph.edges.length} edges`, "#e5e5e5")}
            {badge(`${result.cycles.scc_count} cycle${result.cycles.scc_count !== 1 ? "s" : ""}`,
              result.cycles.scc_count > 0 ? "#fde68a" : "#d1fae5")}
            {badge(result.setup.runtime, "#dbeafe")}
            {badge(`${result.stats.analysis_duration_ms}ms`, "#f3f4f6")}
          </div>

          {/* Commit */}
          <div style={{ marginBottom: 12, color: "#666" }}>
            commit <code>{result.stats.commit_sha.slice(0, 12)}</code>
            &nbsp;·&nbsp;{(result.stats.total_size_bytes / 1024 / 1024).toFixed(1)} MB
          </div>

          {/* Setup */}
          <div style={{ background: "#f9f9f9", border: "1px solid #e5e5e5", borderRadius: 6, padding: 12, marginBottom: 12 }}>
            <strong>Setup</strong>
            <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
              {result.setup.install_cmd && <code style={{ color: "#16a34a" }}>$ {result.setup.install_cmd}</code>}
              {result.setup.build_cmd && <code style={{ color: "#2563eb" }}>$ {result.setup.build_cmd}</code>}
              {result.setup.run_cmd && <code style={{ color: "#7c3aed" }}>$ {result.setup.run_cmd}</code>}
              {result.setup.env_vars.length > 0 && (
                <div style={{ color: "#666", marginTop: 4 }}>
                  env vars: {result.setup.env_vars.join(", ")}
                </div>
              )}
            </div>
          </div>

          {/* Cycles */}
          {result.cycles.scc_count > 0 && (
            <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 6, padding: 12, marginBottom: 12 }}>
              <strong>Circular dependencies ({result.cycles.node_count_in_cycles} files involved)</strong>
              {result.cycles.sccs.slice(0, 3).map((scc, i) => (
                <div key={i} style={{ marginTop: 6, color: "#92400e", fontSize: 12 }}>
                  {scc.join(" → ")} → …
                </div>
              ))}
            </div>
          )}

          {/* Edges */}
          <div style={{ background: "#f9f9f9", border: "1px solid #e5e5e5", borderRadius: 6, padding: 12 }}>
            <strong>Edges</strong>
            <div style={{ marginTop: 6, maxHeight: 240, overflowY: "auto" }}>
              {result.graph.edges.slice(0, 30).map((e, i) => (
                <div key={i} style={{ padding: "2px 0", borderBottom: "1px solid #eee", color: e.is_cycle ? "#dc2626" : "inherit" }}>
                  <code>{e.source}</code> → <code>{e.target}</code>
                  {e.symbol && <span style={{ color: "#666" }}> ({e.symbol})</span>}
                  {e.is_cycle && <span style={{ color: "#dc2626" }}> ⚠ cycle</span>}
                </div>
              ))}
              {result.graph.edges.length > 30 && (
                <div style={{ color: "#999", marginTop: 4 }}>…and {result.graph.edges.length - 30} more</div>
              )}
            </div>
          </div>

        </div>
      )}
    </div>
  );
}
