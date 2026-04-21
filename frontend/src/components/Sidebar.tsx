import { ReactNode, useState } from "react";
import { Edge, Node, SetupSteps, Stats } from "../graph/types";

interface SidebarProps {
  selectedNode: Node | null;
  nodes: Node[];
  edges: Edge[];
  cycles: string[][];
  setup: SetupSteps | null;
  stats: Stats | null;
  onSelectNode: (id: string) => void;
  onHighlightCycle: (nodes: string[] | null) => void;
}

function nodeId(n: string | Node): string {
  return typeof n === "string" ? n : n.id;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      style={{
        border: "none",
        background: "none",
        cursor: "pointer",
        fontSize: 11,
        color: "#6b7280",
        padding: "0 4px",
        flexShrink: 0,
      }}
    >
      {copied ? "✓" : "copy"}
    </button>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ borderTop: "1px solid #e5e7eb", paddingTop: 12, marginBottom: 4 }}>
      <div
        onClick={() => setOpen((v) => !v)}
        style={{
          cursor: "pointer",
          fontWeight: 600,
          fontSize: 13,
          marginBottom: open ? 8 : 0,
          display: "flex",
          justifyContent: "space-between",
          userSelect: "none",
        }}
      >
        <span>{title}</span>
        <span style={{ color: "#9ca3af", fontSize: 11 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && children}
    </div>
  );
}

function CommandLine({ label, cmd, color }: { label: string; cmd: string; color: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 2 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <code
          style={{
            flex: 1,
            background: "#f3f4f6",
            padding: "4px 8px",
            borderRadius: 4,
            fontSize: 11,
            color,
            wordBreak: "break-all",
          }}
        >
          $ {cmd}
        </code>
        <CopyButton text={cmd} />
      </div>
    </div>
  );
}

export function Sidebar({
  selectedNode,
  edges,
  cycles,
  setup,
  stats,
  onSelectNode,
  onHighlightCycle,
}: SidebarProps) {
  const hasContent = selectedNode || setup || cycles.length > 0;

  return (
    <div
      style={{
        width: 360,
        minWidth: 360,
        borderLeft: "1px solid #e5e7eb",
        padding: "12px 14px",
        overflowY: "auto",
        fontFamily: "monospace",
        fontSize: 13,
        background: "#fafafa",
      }}
    >
      {!hasContent && (
        <div style={{ color: "#9ca3af", marginTop: 8 }}>
          Click a node to inspect it.
        </div>
      )}

      {/* ── Selected file ── */}
      {selectedNode && (
        <Section title="Selected file">
          <div style={{ marginBottom: 6 }}>
            {stats?.repo_url && stats?.commit_sha ? (
              <a
                href={`${stats.repo_url}/blob/${stats.commit_sha}/${selectedNode.id}`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "#2563eb", wordBreak: "break-all", fontSize: 12 }}
              >
                {selectedNode.id}
              </a>
            ) : (
              <span style={{ wordBreak: "break-all", fontSize: 12 }}>
                {selectedNode.id}
              </span>
            )}
          </div>

          <div style={{ color: "#6b7280", fontSize: 12, marginBottom: 8 }}>
            {selectedNode.language} · {selectedNode.size} LOC
            {selectedNode.is_cycle && (
              <span style={{ color: "#e11d48", marginLeft: 8 }}>⚠ cycle</span>
            )}
          </div>

          {/* Imports (outgoing) */}
          {(() => {
            const out = edges.filter((e) => nodeId(e.source) === selectedNode.id);
            if (!out.length) return null;
            return (
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 12 }}>
                  Imports ({out.length})
                </div>
                <div style={{ maxHeight: 120, overflowY: "auto" }}>
                  {out.slice(0, 25).map((e, i) => {
                    const t = nodeId(e.target);
                    return (
                      <div
                        key={i}
                        onClick={() => onSelectNode(t)}
                        style={{
                          cursor: "pointer",
                          color: "#2563eb",
                          padding: "1px 0",
                          fontSize: 11,
                        }}
                      >
                        · {t}
                      </div>
                    );
                  })}
                  {out.length > 25 && (
                    <div style={{ color: "#9ca3af", fontSize: 11 }}>
                      +{out.length - 25} more
                    </div>
                  )}
                </div>
              </div>
            );
          })()}

          {/* Imported by (incoming) */}
          {(() => {
            const inc = edges.filter((e) => nodeId(e.target) === selectedNode.id);
            if (!inc.length) return null;
            return (
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 12 }}>
                  Imported by ({inc.length})
                </div>
                <div style={{ maxHeight: 120, overflowY: "auto" }}>
                  {inc.slice(0, 25).map((e, i) => {
                    const s = nodeId(e.source);
                    return (
                      <div
                        key={i}
                        onClick={() => onSelectNode(s)}
                        style={{
                          cursor: "pointer",
                          color: "#2563eb",
                          padding: "1px 0",
                          fontSize: 11,
                        }}
                      >
                        · {s}
                      </div>
                    );
                  })}
                  {inc.length > 25 && (
                    <div style={{ color: "#9ca3af", fontSize: 11 }}>
                      +{inc.length - 25} more
                    </div>
                  )}
                </div>
              </div>
            );
          })()}

          <button
            disabled
            title="Coming in Phase 8"
            style={{
              marginTop: 4,
              padding: "4px 10px",
              fontSize: 11,
              border: "1px solid #e5e7eb",
              borderRadius: 4,
              background: "#f9f9f9",
              color: "#9ca3af",
              cursor: "not-allowed",
            }}
          >
            Explain this file (Phase 8)
          </button>
        </Section>
      )}

      {/* ── Setup ── */}
      {setup && (
        <Section title={`Setup · ${setup.runtime}`}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {setup.install_cmd && (
              <CommandLine label="Install" cmd={setup.install_cmd} color="#16a34a" />
            )}
            {setup.build_cmd && (
              <CommandLine label="Build" cmd={setup.build_cmd} color="#2563eb" />
            )}
            {setup.run_cmd && (
              <CommandLine label="Run" cmd={setup.run_cmd} color="#7c3aed" />
            )}
            {setup.env_vars.length > 0 && (
              <div>
                <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 2 }}>
                  Env vars
                </div>
                <div style={{ fontSize: 11, color: "#374151" }}>
                  {setup.env_vars.join(", ")}
                </div>
              </div>
            )}
            {setup.notes.map((n, i) => (
              <div key={i} style={{ fontSize: 11, color: "#6b7280" }}>
                · {n}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── Cycles ── */}
      {cycles.length > 0 && (
        <Section title={`Cycles (${cycles.length})`}>
          {cycles.map((scc, i) => (
            <div
              key={i}
              style={{
                background: "#fffbeb",
                border: "1px solid #fde68a",
                borderRadius: 6,
                padding: 8,
                marginBottom: 8,
              }}
            >
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  marginBottom: 4,
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <span>{scc.length} files</span>
                <button
                  onClick={() => onHighlightCycle(scc)}
                  style={{
                    padding: "1px 8px",
                    fontSize: 11,
                    border: "1px solid #f59e0b",
                    borderRadius: 4,
                    background: "white",
                    cursor: "pointer",
                    color: "#92400e",
                  }}
                >
                  Highlight
                </button>
              </div>
              <div style={{ maxHeight: 80, overflowY: "auto" }}>
                {scc.map((id, j) => (
                  <div
                    key={j}
                    onClick={() => onSelectNode(id)}
                    style={{
                      cursor: "pointer",
                      color: "#92400e",
                      fontSize: 11,
                      padding: "1px 0",
                    }}
                  >
                    · {id}
                  </div>
                ))}
              </div>
            </div>
          ))}
          <button
            onClick={() => onHighlightCycle(null)}
            style={{
              padding: "3px 10px",
              fontSize: 11,
              border: "1px solid #e5e7eb",
              borderRadius: 4,
              background: "white",
              cursor: "pointer",
              color: "#6b7280",
            }}
          >
            Clear highlight
          </button>
        </Section>
      )}
    </div>
  );
}
