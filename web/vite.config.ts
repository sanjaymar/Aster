import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import type { Plugin } from "postcss";

// The full PDF viewer stylesheet defines generic .sidebar/.dialog classes.
// Only its text-selection layer belongs in our canvas-based reader.
const pdfTextLayer: Plugin = {
    postcssPlugin: "aster-pdf-text-layer",
    Once(root) {
        if (!root.source?.input.file?.endsWith("/pdf_viewer.css")) return;
        const layer = root.nodes.find(
            (node) => node.type === "rule" && node.selector === ".textLayer",
        );
        if (!layer || layer.type !== "rule")
            throw new Error("PDF.js text layer stylesheet is missing");
        const copyright = root.nodes.find((node) => node.type === "comment")?.clone();
        layer.selector = ".pdf-sheet .textLayer";
        layer.remove();
        root.removeAll();
        if (copyright) root.append(copyright);
        root.append(layer);
    },
};

export default defineConfig({
    plugins: [react()],
    css: { postcss: { plugins: [pdfTextLayer] } },
    server: { proxy: { "/api": "http://127.0.0.1:8765" } },
    build: { outDir: "../src/aster/static", emptyOutDir: true },
});
