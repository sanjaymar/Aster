import {
    TextLayer,
    type PDFDocumentProxy,
    type RenderTask,
} from "pdfjs-dist/legacy/build/pdf.mjs";
import { useEffect, useRef, useState } from "react";
import type { Annotation } from "../../shared/api";
import { Spinner } from "../../shared/ui";
export type OutlineItem = { title: string; page: number; depth: number };
export function PdfPage({
    document,
    page,
    zoom,
    annotations,
    onReady,
    onSelection,
}: {
    document: PDFDocumentProxy;
    page: number;
    zoom: number;
    annotations: Annotation[];
    onReady: () => void;
    onSelection: (rectangles: number[][]) => void;
}) {
    const [error, setError] = useState(""),
        [busy, setBusy] = useState(true),
        [width, setWidth] = useState(700);
    const holder = useRef<HTMLDivElement>(null),
        canvas = useRef<HTMLCanvasElement>(null),
        layer = useRef<HTMLDivElement>(null),
        callbacks = useRef({ onReady });
    callbacks.current = { onReady };
    useEffect(() => {
        if (!holder.current) return;
        const observer = new ResizeObserver((entries) =>
            setWidth(entries[0].contentRect.width),
        );
        observer.observe(holder.current);
        return () => observer.disconnect();
    }, []);
    useEffect(() => {
        if (!document || !canvas.current || !layer.current) return;
        let cancelled = false,
            render: RenderTask | undefined,
            textLayer: TextLayer | undefined;
        setBusy(true);
        void (async () => {
            const pdfPage = await document.getPage(page);
            if (cancelled || !canvas.current || !layer.current) return;
            const natural = pdfPage.getViewport({ scale: 1 });
            const viewport = pdfPage.getViewport({
                scale: Math.max(0.2, (width - 48) / natural.width) * zoom,
            });
            const element = canvas.current,
                context = element.getContext("2d");
            if (!context) return;
            const ratio = window.devicePixelRatio || 1;
            element.width = Math.floor(viewport.width * ratio);
            element.height = Math.floor(viewport.height * ratio);
            element.style.width = `${viewport.width}px`;
            element.style.height = `${viewport.height}px`;
            const sheet = element.parentElement!;
            sheet.style.width = `${viewport.width}px`;
            sheet.style.height = `${viewport.height}px`;
            sheet.style.setProperty("--scale-factor", String(viewport.scale));
            sheet.style.setProperty(
                "--total-scale-factor",
                String(viewport.scale),
            );
            render = pdfPage.render({
                canvas: element,
                canvasContext: context,
                viewport,
                transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
            });
            await render.promise;
            if (cancelled) return;
            layer.current.replaceChildren();
            textLayer = new TextLayer({
                textContentSource: await pdfPage.getTextContent(),
                container: layer.current,
                viewport,
            });
            await textLayer.render();
            if (!cancelled) {
                setBusy(false);
                callbacks.current.onReady();
            }
        })().catch((error) => {
            if (!cancelled && error.name !== "RenderingCancelledException") {
                setError(error.message);
                setBusy(false);
            }
        });
        return () => {
            cancelled = true;
            render?.cancel();
            textLayer?.cancel();
        };
    }, [document, page, zoom, width]);
    function selected() {
        const selection = window.getSelection();
        if (
            !selection?.rangeCount ||
            !layer.current?.contains(selection.anchorNode) ||
            !layer.current?.contains(selection.focusNode)
        )
            return;
        const range = selection.getRangeAt(0),
            sheet = canvas.current?.getBoundingClientRect();
        if (!sheet) return;
        const rectangles = Array.from(range.getClientRects())
            .filter((rect) => rect.width > 0 && rect.height > 0)
            .map((rect) => [
                Math.max(0, (rect.left - sheet.left) / sheet.width),
                Math.max(0, (rect.top - sheet.top) / sheet.height),
                Math.min(1, rect.width / sheet.width),
                Math.min(1, rect.height / sheet.height),
            ]);
        onSelection(rectangles);
    }
    return (
        <div className="pdf-page-holder" ref={holder}>
            {busy && !error && (
                <div className="pdf-loading">
                    <Spinner />
                </div>
            )}
            {error && <p className="error-text">{error}</p>}
            <div className="pdf-sheet" onMouseUp={selected}>
                <canvas ref={canvas} />
                <div ref={layer} className="textLayer" />
                {annotations.flatMap((annotation) =>
                    annotation.rectangles.map((rect, i) => (
                        <span
                            key={`${annotation.id}-${i}`}
                            className="pdf-highlight"
                            style={{
                                left: `${rect[0] * 100}%`,
                                top: `${rect[1] * 100}%`,
                                width: `${rect[2] * 100}%`,
                                height: `${rect[3] * 100}%`,
                            }}
                            title={annotation.comment || annotation.quote}
                        />
                    )),
                )}
            </div>
        </div>
    );
}
