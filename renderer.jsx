import React from "react";
import { createRoot } from "react-dom/client";
import App from "./anti-gomoku.jsx";

const mountNode = document.getElementById("root");
if (!mountNode) {
  throw new Error("Root mount node was not found.");
}

createRoot(mountNode).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
