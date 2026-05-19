/**
 * Professional dark/light theme for DepGraph
 * Inspired by GitHub's design system
 */

export interface Theme {
  // Core colors
  bg: string;
  bgSecondary: string;
  bgTertiary: string;
  text: string;
  textSubtle: string;
  textMuted: string;
  
  // UI elements
  border: string;
  borderSubtle: string;
  
  // Components
  panelBg: string;
  panelBorder: string;
  
  // Inputs
  inputBg: string;
  inputBorder: string;
  inputText: string;
  
  // Buttons
  buttonBg: string;
  buttonText: string;
  buttonHover: string;
  
  // Status/Accents
  primary: string;
  success: string;
  warning: string;
  error: string;
  
  // Links
  link: string;
  linkHover: string;
}

export const lightTheme: Theme = {
  bg: "#ffffff",
  bgSecondary: "#f6f8fa",
  bgTertiary: "#f3f4f6",
  text: "#111827",
  textSubtle: "#6b7280",
  textMuted: "#9ca3af",
  
  border: "#e5e7eb",
  borderSubtle: "#d1d5db",
  
  panelBg: "#ffffff",
  panelBorder: "#e5e7eb",
  
  inputBg: "#ffffff",
  inputBorder: "#d1d5db",
  inputText: "#111827",
  
  buttonBg: "#1a1a1a",
  buttonText: "#ffffff",
  buttonHover: "#333333",
  
  primary: "#2563eb",
  success: "#16a34a",
  warning: "#ea580c",
  error: "#dc2626",
  
  link: "#2563eb",
  linkHover: "#1d4ed8",
};

export const darkTheme: Theme = {
  // GitHub-inspired dark mode with proper contrast
  bg: "#0d1117",
  bgSecondary: "#161b22",
  bgTertiary: "#1c2128",
  text: "#e6edf3",
  textSubtle: "#8b949e",
  textMuted: "#6e7681",
  
  border: "#30363d",
  borderSubtle: "#21262d",
  
  panelBg: "#0d1117",
  panelBorder: "#30363d",
  
  inputBg: "#0d1117",
  inputBorder: "#30363d",
  inputText: "#e6edf3",
  
  buttonBg: "#238636",
  buttonText: "#ffffff",
  buttonHover: "#2ea043",
  
  primary: "#58a6ff",
  success: "#3fb950",
  warning: "#d29922",
  error: "#f85149",
  
  link: "#58a6ff",
  linkHover: "#79c0ff",
};

export function getTheme(darkMode: boolean): Theme {
  return darkMode ? darkTheme : lightTheme;
}
