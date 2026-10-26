import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";
import { SummaryProvider } from "./summary";
import { UiProvider } from "./ui";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <HashRouter>
      <AuthProvider>
        <UiProvider>
          <SummaryProvider>
            <App />
          </SummaryProvider>
        </UiProvider>
      </AuthProvider>
    </HashRouter>
  </StrictMode>,
);
