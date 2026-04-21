import { useState } from "react";

const API = import.meta.env.VITE_API_URL ?? "/api";

interface Edge {
  source: string;
  target: string;
  type: string;
  symbol: string | null;
  line: number;
}

interface Node {
  id: string;
  label: string;
  language: string;
  size: number;
  cluster: string;
  parse_error: boolean;
}

interface AnalyzeResult {
  job_id: string;
  commit_sha: string;
  file_count: number;
  total_size_bytes: number;
  nodes: Node[];
  edges: Edge[];
}

export default function App() {
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<AnalyzeResult | null>(null);
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
    <div style={{ fontFamily: "monospace", maxWidth: 640, margin: "80px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 32, marginBottom: 8 }}>DepGraph</h1>
      <p style={{ color: "#666", marginBottom: 32 }}>
        Paste a GitHub / GitLab / Bitbucket URL to analyse its file structure.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8 }}>
        <input
          type="url"
          required
          placeholder="https://github.com/tiangolo/fastapi"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          style={{
            flex: 1,
            padding: "8px 12px",
            fontSize: 14,
            border: "1px solid #ccc",
            borderRadius: 4,
          }}
        />
        <button
          type="submit"
          disabled={loading}
          style={{
            padding: "8px 20px",
            fontSize: 14,
            background: "#1a1a1a",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Analysing…" : "Analyse"}
        </button>
      </form>

      {loading && (
        <p style={{ marginTop: 24, color: "#666" }}>Cloning repo, this takes a few seconds…</p>
      )}

      {result && (
        <div style={{ marginTop: 24, background: "#f9f9f9", border: "1px solid #e5e5e5", borderRadius: 6, padding: 16 }}>
          <div style={{ marginBottom: 8 }}>
            <strong>job_id:</strong> <code style={{ fontSize: 12 }}>{result.job_id}</code>
          </div>
          <div style={{ marginBottom: 8 }}>
            <strong>commit:</strong> <code style={{ fontSize: 12 }}>{result.commit_sha.slice(0, 12)}</code>
          </div>
          <div style={{ marginBottom: 8 }}>
            <strong>files:</strong> {result.file_count}
          </div>
          <div style={{ marginBottom: 8 }}>
            <strong>size:</strong> {(result.total_size_bytes / 1024 / 1024).toFixed(2)} MB
          </div>
          <div style={{ marginBottom: 8 }}>
            <strong>nodes:</strong> {result.nodes.length} &nbsp;
            <strong>edges:</strong> {result.edges.length}
          </div>
          <div>
            <strong>sample edges:</strong>
            <div style={{ marginTop: 6, fontSize: 12, maxHeight: 200, overflowY: "auto" }}>
              {result.edges.slice(0, 20).map((e, i) => (
                <div key={i} style={{ padding: "2px 0", borderBottom: "1px solid #eee" }}>
                  <code>{e.source}</code> → <code>{e.target}</code>
                  {e.symbol && <span style={{ color: "#666" }}> ({e.symbol})</span>}
                </div>
              ))}
              {result.edges.length > 20 && (
                <div style={{ color: "#999", marginTop: 4 }}>…and {result.edges.length - 20} more</div>
              )}
            </div>
          </div>
        </div>
      )}

      {error && (
        <p style={{ marginTop: 24, color: "#dc2626" }}>Error: {error}</p>
      )}
    </div>
  );
}
