import { useState } from "react";

const API = import.meta.env.VITE_API_URL ?? "/api";

export default function App() {
  const [url, setUrl] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setJobId(null);
    try {
      const res = await fetch(`${API}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      console.log("job_id:", data.job_id);
      setJobId(data.job_id);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ fontFamily: "monospace", maxWidth: 600, margin: "80px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 32, marginBottom: 8 }}>DepGraph</h1>
      <p style={{ color: "#666", marginBottom: 32 }}>Paste a package URL to analyse its dependency graph.</p>

      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8 }}>
        <input
          type="url"
          required
          placeholder="https://registry.npmjs.org/react"
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
          {loading ? "Submitting…" : "Analyse"}
        </button>
      </form>

      {jobId && (
        <p style={{ marginTop: 24, color: "#16a34a" }}>
          Job queued — <code>{jobId}</code> (check browser console)
        </p>
      )}
      {error && (
        <p style={{ marginTop: 24, color: "#dc2626" }}>Error: {error}</p>
      )}
    </div>
  );
}
