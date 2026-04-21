import { Progress } from "../graph/types";

interface Props {
  loading: boolean;
  statusMsg: string | null;
  progress: Progress | null;
}

export function ProgressBar({ loading, statusMsg, progress }: Props) {
  if (!loading) return null;

  const pct =
    progress && progress.total > 0
      ? Math.round((progress.done / progress.total) * 100)
      : 0;

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 10,
        background: "rgba(255,255,255,0.96)",
        padding: "8px 12px",
        borderBottom: "1px solid #e5e7eb",
      }}
    >
      <div
        style={{
          background: "#e5e7eb",
          borderRadius: 4,
          height: 4,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            background: "#1a1a1a",
            height: "100%",
            width: `${pct}%`,
            transition: "width 0.15s ease",
          }}
        />
      </div>
      {statusMsg && (
        <div
          style={{
            marginTop: 4,
            fontSize: 11,
            color: "#6b7280",
            fontFamily: "monospace",
          }}
        >
          {statusMsg}
          {progress && progress.total > 0 && (
            <span style={{ marginLeft: 8 }}>
              {progress.done} / {progress.total}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
