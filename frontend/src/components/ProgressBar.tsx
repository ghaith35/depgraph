import { Progress } from "../graph/types";

interface Props {
  loading: boolean;
  statusMsg: string | null;
  progress: Progress | null;
  darkMode?: boolean;
}

export function ProgressBar({ loading, statusMsg, progress, darkMode = false }: Props) {
  if (!loading) return null;

  const bg = darkMode ? "#0d1117" : "#ffffff";
  const border = darkMode ? "#30363d" : "#e5e7eb";
  const text = darkMode ? "#8b949e" : "#6b7280";
  const progressBg = darkMode ? "#21262d" : "#e5e7eb";
  const progressFill = darkMode ? "#58a6ff" : "#1a1a1a";

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
        background: darkMode ? "rgba(13, 17, 23, 0.96)" : "rgba(255, 255, 255, 0.96)",
        padding: "8px 12px",
        borderBottom: `1px solid ${border}`,
        backdropFilter: "blur(10px)",
      }}
    >
      <div
        style={{
          background: progressBg,
          borderRadius: 4,
          height: 4,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            background: progressFill,
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
            color: text,
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
