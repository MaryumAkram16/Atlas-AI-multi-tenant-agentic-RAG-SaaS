import { useState } from "react";
import { applyTheme, storedTheme, type Theme } from "../services/theme";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => storedTheme());
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" className="btn btn-ghost theme-toggle" aria-label={`Switch to ${next} theme`}
      onClick={() => {
        applyTheme(next);
        setTheme(next);
      }}>
      {theme === "dark" ? "☀ Light mode" : "☾ Dark mode"}
    </button>
  );
}
