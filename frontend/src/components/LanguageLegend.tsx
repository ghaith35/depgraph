import { languageColor } from "../graph/colors";
import { Node } from "../graph/types";

interface Props {
  nodes: Node[];
}

export function LanguageLegend({ nodes }: Props) {
  const langs = [...new Set(nodes.map((n) => n.language))]
    .filter((l) => l !== "other")
    .sort();

  if (langs.length === 0) return null;

  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        flexWrap: "wrap",
        background: "rgba(255,255,255,0.92)",
        padding: "5px 10px",
        borderRadius: 6,
        fontSize: 11,
        fontFamily: "monospace",
        border: "1px solid #e5e7eb",
      }}
    >
      {langs.map((lang) => (
        <span
          key={lang}
          style={{ display: "flex", alignItems: "center", gap: 4 }}
        >
          <span
            style={{
              width: 9,
              height: 9,
              borderRadius: "50%",
              background: languageColor(lang),
              display: "inline-block",
              border: "1px solid rgba(0,0,0,0.15)",
              flexShrink: 0,
            }}
          />
          {lang}
        </span>
      ))}
    </div>
  );
}
