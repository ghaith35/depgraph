import { useRef, useState } from "react";

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

interface SetupSteps {
  runtime: string;
  install_cmd: string | null;
  build_cmd: string | null;
  run_cmd: string | null;
  env_vars: string[];
  notes: string[];
}

interface Stats {
  file_count: number;
  total_size_bytes: number;
  languages: Record<string, number>;
  commit_sha: string;
  analysis_duration_ms: number;
}

interface Progress {
  done: number;
  total: number;
  phase: string;
}

const badge = (text: string, color: string) => (
  <span style={{ background: color, borderRadius: 4, padding: "2px 8px", fontSize: 12, marginRight: 4 }}>
    {text}
  </span>
);

export default function App() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [cycles, setCycles] = useState<string[][]>([]);
  const [setup, setSetup] = useState<SetupSteps | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);

  const esRef = useRef<EventSource | null>(null);
  const doneRef = useRef(false);

  function closeStream() {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    closeStream();
    doneRef.current = false;
    setLoading(true);
    setError(null);
    setStatusMsg(null);
    setProgress(null);
    setNodes([]);
    setEdges([]);
    setCycles([]);
    setSetup(null);
    setStats(null);

    try {
      const res = await fetch(`${API}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);

      const jobId: string = data.job_id;
      const es = new EventSource(`${API}/stream/${jobId}`);
      esRef.current = es;

      es.addEventListener("status", (ev) => {
        const d = JSON.parse((ev as MessageEvent).data);
        setStatusMsg(d.message);
      });

      es.addEventListener("progress", (ev) => {
        setProgress(JSON.parse((ev as MessageEvent).data));
      });

      es.addEventListener("node", (ev) => {
        const node: Node = JSON.parse((ev as MessageEvent).data);
        setNodes((prev) => [...prev, node]);
      });

      es.addEventListener("edge", (ev) => {
        const edge: Edge = JSON.parse((ev as MessageEvent).data);
        setEdges((prev) => [...prev, edge]);
      });

      es.addEventListener("cycle", (ev) => {
        const d = JSON.parse((ev as MessageEvent).data);
        setCycles((prev) => [...prev, d.nodes as string[]]);
      });

      es.addEventListener("setup", (ev) => {
        setSetup(JSON.parse((ev as MessageEvent).data));
      });

      es.addEventListener("stats", (ev) => {
        setStats(JSON.parse((ev as MessageEvent).data));
      });

      es.addEventListener("done", () => {
        doneRef.current = true;
        setLoading(false);
        setStatusMsg(null);
        closeStream();
      });

      es.addEventListener("error", (ev) => {
        // SSE application-level error frame
        try {
          const d = JSON.parse((ev as MessageEvent).data);
          setError(d.message ?? "Analysis failed");
        } catch {
          setError("Analysis failed");
        }
        doneRef.current = true;
        setLoading(false);
        closeStream();
      });

      es.onerror = () => {
        // Network-level error (not an SSE frame)
        if (!doneRef.current) {
          setError("Stream connection lost");
          setLoading(false);
        }
        closeStream();
      };

    } catch (err) {
      setError(String(err));
      setLoading(false);
    }
  }

  const hasSomeData = nodes.length > 0 || stats !== null;

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

      {error && <p style={{ color: "#dc2626", fontSize: 13 }}>Error: {error}</p>}

      {(loading || hasSomeData) && (
        <div style={{ fontSize: 13 }}>

          {/* Status / progress bar */}
          {loading && (
            <div style={{ marginBottom: 14 }}>
              {statusMsg && (
                <p style={{ color: "#666", margin: "0 0 6px", fontSize: 13 }}>{statusMsg}</p>
              )}
              {progress && (
                <div>
                  <div style={{ background: "#e5e7eb", borderRadius: 4, height: 6, overflow: "hidden" }}>
                    <div style={{
                      background: "#1a1a1a",
                      height: "100%",
                      width: `${progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0}%`,
                      transition: "width 0.15s ease",
                    }} />
                  </div>
                  <p style={{ color: "#999", margin: "4px 0 0", fontSize: 11 }}>
                    {progress.done} / {progress.total} files parsed
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Stats badges */}
          {hasSomeData && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              {badge(`${nodes.length} files`, "#e5e5e5")}
              {badge(`${edges.length} edges`, "#e5e5e5")}
              {cycles.length > 0
                ? badge(`${cycles.length} cycle${cycles.length !== 1 ? "s" : ""}`, "#fde68a")
                : badge("0 cycles", "#d1fae5")}
              {setup && badge(setup.runtime, "#dbeafe")}
              {stats && badge(`${stats.analysis_duration_ms}ms`, "#f3f4f6")}
            </div>
          )}

          {/* Commit / size */}
          {stats && (
            <div style={{ marginBottom: 12, color: "#666" }}>
              commit <code>{stats.commit_sha.slice(0, 12)}</code>
              &nbsp;·&nbsp;{(stats.total_size_bytes / 1024 / 1024).toFixed(1)} MB
            </div>
          )}

          {/* Setup */}
          {setup && (
            <div style={{ background: "#f9f9f9", border: "1px solid #e5e5e5", borderRadius: 6, padding: 12, marginBottom: 12 }}>
              <strong>Setup</strong>
              <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
                {setup.install_cmd && <code style={{ color: "#16a34a" }}>$ {setup.install_cmd}</code>}
                {setup.build_cmd && <code style={{ color: "#2563eb" }}>$ {setup.build_cmd}</code>}
                {setup.run_cmd && <code style={{ color: "#7c3aed" }}>$ {setup.run_cmd}</code>}
                {setup.env_vars.length > 0 && (
                  <div style={{ color: "#666", marginTop: 4 }}>
                    env vars: {setup.env_vars.join(", ")}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Cycles */}
          {cycles.length > 0 && (
            <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 6, padding: 12, marginBottom: 12 }}>
              <strong>Circular dependencies ({cycles.reduce((s, c) => s + c.length, 0)} files involved)</strong>
              {cycles.slice(0, 3).map((scc, i) => (
                <div key={i} style={{ marginTop: 6, color: "#92400e", fontSize: 12 }}>
                  {scc.join(" → ")} → …
                </div>
              ))}
            </div>
          )}

          {/* Edges */}
          {edges.length > 0 && (
            <div style={{ background: "#f9f9f9", border: "1px solid #e5e5e5", borderRadius: 6, padding: 12 }}>
              <strong>Edges</strong>
              <div style={{ marginTop: 6, maxHeight: 240, overflowY: "auto" }}>
                {edges.slice(0, 30).map((e, i) => (
                  <div key={i} style={{ padding: "2px 0", borderBottom: "1px solid #eee", color: e.is_cycle ? "#dc2626" : "inherit" }}>
                    <code>{e.source}</code> → <code>{e.target}</code>
                    {e.symbol && <span style={{ color: "#666" }}> ({e.symbol})</span>}
                    {e.is_cycle && <span style={{ color: "#dc2626" }}> ⚠ cycle</span>}
                  </div>
                ))}
                {edges.length > 30 && (
                  <div style={{ color: "#999", marginTop: 4 }}>…and {edges.length - 30} more</div>
                )}
              </div>
            </div>
          )}

        </div>
      )}
    </div>
  );
}
