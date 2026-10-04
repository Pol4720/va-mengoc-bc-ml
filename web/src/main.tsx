import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";
import { applyThemeChoice, loadThemeChoice } from "./theme";

// Apply the stored theme before the first render so charts read the right tokens.
applyThemeChoice(loadThemeChoice());

const el = document.getElementById("root");
if (!el) throw new Error("#root not found");
createRoot(el).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
