import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { applyTheme, storedTheme } from "./services/theme";
import "./styles.css";

applyTheme(storedTheme()); // before the first paint: no flash of the wrong theme

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
