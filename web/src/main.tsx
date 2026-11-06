import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/base.css";
import "./styles/documents.css";
import "./styles/library.css";
import "./styles/reader.css";
import "./styles/settings.css";
import "./styles/notebook.css";
import "katex/dist/katex.min.css";
createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
        <App />
    </React.StrictMode>,
);
