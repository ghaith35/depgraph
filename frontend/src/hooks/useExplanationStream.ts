import { useCallback, useRef, useState } from "react";

const API = import.meta.env.VITE_API_URL ?? "/api";

export type ExplanationStatus =
  | "idle"
  | "streaming"
  | "done"
  | "error"
  | "replaced";

export interface ExplanationState {
  status: ExplanationStatus;
  text: string;
  statusMessage: string | null;
  redactionCount: number;
  error: string | null;
  replacedMessage: string | null;
}

const INITIAL: ExplanationState = {
  status: "idle",
  text: "",
  statusMessage: null,
  redactionCount: 0,
  error: null,
  replacedMessage: null,
};

export function useExplanationStream() {
  const [state, setState] = useState<ExplanationState>(INITIAL);
  const esRef = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    close();
    setState(INITIAL);
  }, [close]);

  const explain = useCallback(
    (jobId: string, filePath: string) => {
      close();
      setState({ ...INITIAL, status: "streaming", statusMessage: "Connecting…" });

      const encoded = filePath.split("/").map(encodeURIComponent).join("/");
      const url = `${API}/explain/${jobId}/${encoded}`;
      const es = new EventSource(url);
      esRef.current = es;

      es.addEventListener("status", (ev) => {
        const d = JSON.parse((ev as MessageEvent).data);
        setState((p) => ({ ...p, statusMessage: d.message ?? null }));
      });

      es.addEventListener("ai.redacted", (ev) => {
        const d = JSON.parse((ev as MessageEvent).data);
        setState((p) => ({ ...p, redactionCount: d.count ?? 0 }));
      });

      es.addEventListener("ai.token", (ev) => {
        const d = JSON.parse((ev as MessageEvent).data);
        setState((p) => ({
          ...p,
          statusMessage: null,
          text: p.text + (d.text ?? ""),
        }));
      });

      es.addEventListener("ai.done", () => {
        setState((p) => ({ ...p, status: "done", statusMessage: null }));
        close();
      });

      es.addEventListener("ai.replaced", (ev) => {
        const d = JSON.parse((ev as MessageEvent).data);
        setState((p) => ({
          ...p,
          status: "replaced",
          statusMessage: null,
          text: "",
          replacedMessage: d.message ?? "Could not generate explanation.",
        }));
        close();
      });

      es.addEventListener("ai.truncated", (ev) => {
        const d = JSON.parse((ev as MessageEvent).data);
        setState((p) => ({
          ...p,
          status: "error",
          statusMessage: null,
          error: d.message ?? "Explanation cut off.",
        }));
        close();
      });

      es.addEventListener("error", (ev) => {
        try {
          const d = JSON.parse((ev as MessageEvent).data);
          setState((p) => ({
            ...p,
            status: "error",
            statusMessage: null,
            error: d.message ?? "AI explanation unavailable.",
          }));
        } catch {
          setState((p) => ({
            ...p,
            status: "error",
            statusMessage: null,
            error: "AI explanation unavailable.",
          }));
        }
        close();
      });

      es.onerror = () => {
        setState((p) => {
          if (p.status === "streaming" && !p.text) {
            return { ...p, status: "error", error: "Connection lost." };
          }
          return p;
        });
        close();
      };
    },
    [close],
  );

  return { state, explain, reset };
}
