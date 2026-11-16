import "@fontsource-variable/inter";
import "katex/dist/katex.min.css";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
