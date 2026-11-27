/** Light/dark theme, remembered per browser (a convenience only). */
export type Theme = "dark" | "light";
const KEY = "atlas-theme";

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Storage can be blocked (private mode); the theme still applies for this visit.
  }
}
