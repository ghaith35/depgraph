import { useCallback, useEffect, useRef, useState } from "react";
import { Edge, Node, Progress, SetupSteps, Stats } from "../graph/types";

const API = import.meta.env.VITE_API_URL ?? "/api";

export interface AnalysisState {
  loading: boolean;
  error: string | null;
  statusMsg: string | null;
  progress: Progress | null;
  nodes: Node[];
  edges: Edge[];
  cycles: string[][];
  setup: SetupSteps | null;
  stats: Stats | null;
}

const INITIAL: AnalysisState = {
  loading: false,
  error: null,
  statusMsg: null,
  progress: null,
  nodes: [],
  edges: [],
  cycles: [],
  setup: null,
  stats: null,
};

export function useAnalysis() {
  const [state, setState] = useState<AnalysisState>(INITIAL);
  const esRef = useRef<EventSource | null>(null);
  const doneRef = useRef(false);
  // Buffer incoming node/edge events; flushed every 100ms to React state
  const bufRef = useRef<{ nodes: Node[]; edges: Edge[] }>({
    nodes: [],
    edges: [],
  });

  // Flush buffer every 100ms — avoids a React render per SSE frame
  useEffect(() => {
    const id = setInterval(() => {
      const buf = bufRef.current;
      if (buf.nodes.length || buf.edges.length) {
        const ns = buf.nodes.splice(0);
        const es = buf.edges.splice(0);
        setState((p) => ({
          ...p,
          nodes: [...p.nodes, ...ns],
          edges: [...p.edges, ...es],
        }));
      }
    }, 100);
    return () => clearInterval(id);
  }, []);

  const closeStream = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const analyze = useCallback(
    async (url: string) => {
      closeStream();
      doneRef.current = false;
      bufRef.current = { nodes: [], edges: [] };
      setState({ ...INITIAL, loading: true });

      try {
        const res = await fetch(`${API}/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);

        const es = new EventSource(`${API}/stream/${data.job_id}`);
        esRef.current = es;

        es.addEventListener("status", (ev) => {
          const d = JSON.parse((ev as MessageEvent).data);
          setState((p) => ({ ...p, statusMsg: d.message }));
        });

        es.addEventListener("progress", (ev) => {
          setState((p) => ({
            ...p,
            progress: JSON.parse((ev as MessageEvent).data),
          }));
        });

        es.addEventListener("node", (ev) => {
          bufRef.current.nodes.push(JSON.parse((ev as MessageEvent).data));
        });

        es.addEventListener("edge", (ev) => {
          bufRef.current.edges.push(JSON.parse((ev as MessageEvent).data));
        });

        es.addEventListener("cycle", (ev) => {
          const d = JSON.parse((ev as MessageEvent).data);
          setState((p) => ({
            ...p,
            cycles: [...p.cycles, d.nodes as string[]],
          }));
        });

        es.addEventListener("setup", (ev) => {
          setState((p) => ({
            ...p,
            setup: JSON.parse((ev as MessageEvent).data),
          }));
        });

        es.addEventListener("stats", (ev) => {
          setState((p) => ({
            ...p,
            stats: JSON.parse((ev as MessageEvent).data),
          }));
        });

        es.addEventListener("done", () => {
          doneRef.current = true;
          // Flush any remaining buffered data
          const buf = bufRef.current;
          const ns = buf.nodes.splice(0);
          const edges = buf.edges.splice(0);
          setState((p) => ({
            ...p,
            loading: false,
            statusMsg: null,
            nodes: [...p.nodes, ...ns],
            edges: [...p.edges, ...edges],
          }));
          closeStream();
        });

        es.addEventListener("error", (ev) => {
          try {
            const d = JSON.parse((ev as MessageEvent).data);
            setState((p) => ({
              ...p,
              error: d.message ?? "Analysis failed",
              loading: false,
            }));
          } catch {
            setState((p) => ({ ...p, error: "Analysis failed", loading: false }));
          }
          doneRef.current = true;
          closeStream();
        });

        es.onerror = () => {
          if (!doneRef.current) {
            setState((p) => ({
              ...p,
              error: "Stream connection lost",
              loading: false,
            }));
          }
          closeStream();
        };
      } catch (err) {
        setState((p) => ({ ...p, error: String(err), loading: false }));
      }
    },
    [closeStream],
  );

  return { state, analyze };
}
