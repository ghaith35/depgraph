import ReactMarkdown from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import type { Options } from "rehype-sanitize";

// Strict allowlist — no img, iframe, script, or raw HTML
const sanitizeSchema: Options = {
  ...defaultSchema,
  tagNames: [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "ul", "ol", "li",
    "code", "pre",
    "a",
    "strong", "em",
    "blockquote",
    "br",
  ],
  attributes: {
    ...defaultSchema.attributes,
    a: ["href", "title"],
    code: ["className"],
  },
  strip: ["script", "style", "iframe", "img", "object", "embed", "form"],
};

const rehypePlugins = [[rehypeSanitize, sanitizeSchema]] as const;

interface Props {
  text: string;
}

export function ExplanationRenderer({ text }: Props) {
  return (
    <div
      style={{
        fontSize: 12,
        lineHeight: 1.6,
        color: "#1f2937",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <ReactMarkdown
        rehypePlugins={rehypePlugins as never}
        components={{
          // Links: show URL on hover, open new tab, no auto-load
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              title={href}
              style={{ color: "#2563eb", wordBreak: "break-all" }}
              onClick={(e) => e.stopPropagation()}
            >
              {children}
            </a>
          ),
          // Headings — compact for sidebar
          h1: ({ children }) => (
            <div style={{ fontWeight: 700, fontSize: 13, margin: "10px 0 4px" }}>
              {children}
            </div>
          ),
          h2: ({ children }) => (
            <div style={{ fontWeight: 700, fontSize: 12, margin: "8px 0 4px" }}>
              {children}
            </div>
          ),
          h3: ({ children }) => (
            <div style={{ fontWeight: 600, fontSize: 12, margin: "6px 0 2px" }}>
              {children}
            </div>
          ),
          // Inline code
          code: ({ children, className }) => {
            const isBlock = !!className;
            if (isBlock) {
              return (
                <pre
                  style={{
                    background: "#f3f4f6",
                    borderRadius: 4,
                    padding: "6px 8px",
                    overflowX: "auto",
                    fontSize: 11,
                    margin: "4px 0",
                  }}
                >
                  <code>{children}</code>
                </pre>
              );
            }
            return (
              <code
                style={{
                  background: "#f3f4f6",
                  borderRadius: 3,
                  padding: "1px 4px",
                  fontSize: 11,
                  fontFamily: "monospace",
                }}
              >
                {children}
              </code>
            );
          },
          pre: ({ children }) => <>{children}</>,
          p: ({ children }) => (
            <p style={{ margin: "4px 0 8px" }}>{children}</p>
          ),
          ul: ({ children }) => (
            <ul style={{ margin: "4px 0", paddingLeft: 18 }}>{children}</ul>
          ),
          ol: ({ children }) => (
            <ol style={{ margin: "4px 0", paddingLeft: 18 }}>{children}</ol>
          ),
          li: ({ children }) => (
            <li style={{ marginBottom: 2 }}>{children}</li>
          ),
          blockquote: ({ children }) => (
            <blockquote
              style={{
                borderLeft: "3px solid #d1d5db",
                margin: "4px 0",
                paddingLeft: 8,
                color: "#6b7280",
              }}
            >
              {children}
            </blockquote>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
