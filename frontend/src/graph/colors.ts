import { Node } from "./types";

export const LANGUAGE_COLORS: Record<string, string> = {
  python: "#3776AB",
  javascript: "#F7DF1E",
  typescript: "#3178C6",
  java: "#E76F00",
  go: "#00ADD8",
  rust: "#CE422B",
  c: "#555555",
  cpp: "#00599C",
  csharp: "#68217A",
  ruby: "#CC342D",
  php: "#777BB4",
  swift: "#FA7343",
  kotlin: "#7F52FF",
  scala: "#DC322F",
  shell: "#4EAA25",
  other: "#9CA3AF",
};

export function languageColor(lang: string): string {
  return LANGUAGE_COLORS[lang.toLowerCase()] ?? LANGUAGE_COLORS.other;
}

export function nodeRadius(node: Node): number {
  const loc = Math.max(1, node.size);
  return Math.min(30, Math.max(8, 8 + Math.log10(loc + 1) * 4));
}
