import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { YieldUnitProvider } from "./features/yield/YieldUnitContext.jsx";
import "./styles.css";
createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <YieldUnitProvider>
      <App />
    </YieldUnitProvider>
  </React.StrictMode>,
);
