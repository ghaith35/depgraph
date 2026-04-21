import { useState } from "react";

const API = import.meta.env.VITE_API_URL ?? "/api";

interface AnalyzeResult {
  job_id: string;
  commit_sha: string;
  file_count: number;
  total_size_bytes: number;
  languages: Record<string, number>;
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
          <div style={{ marginBottom: 12 }}>
            <strong>size:</strong> {(result.total_size_bytes / 1024 / 1024).toFixed(2)} MB
          </div>
          <div>
            <strong>languages:</strong>
            <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6 }}>
              {Object.entries(result.languages).map(([lang, count]) => (
                <span
                  key={lang}
                  style={{
                    background: "#e5e5e5",
                    borderRadius: 4,
                    padding: "2px 8px",
                    fontSize: 13,
                  }}
                >
                  {lang} {count}
                </span>
              ))}
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
