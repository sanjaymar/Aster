import {
    getDocument,
    GlobalWorkerOptions,
    type PDFDocumentProxy,
} from "pdfjs-dist/legacy/build/pdf.mjs";
import worker from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import { useEffect, useRef, useState } from "react";
import type { Annotation, Span } from "../../shared/api";
import { Spinner } from "../../shared/ui";
import { PdfPage, type OutlineItem } from "./PdfPage";

GlobalWorkerOptions.workerSrc = worker;

function VisiblePage({
    document,
    page,
    width,
    height,
    zoom,
    annotations,
    onSelection,
}: {
    document: PDFDocumentProxy;
    page: number;
    width: number;
    height: number;
    zoom: number;
    annotations: Annotation[];
    onSelection: (page: number, rectangles: number[][]) => void;
}) {
    const ref = useRef<HTMLElement>(null);
    const [visible, setVisible] = useState(false),
        [availableWidth, setAvailableWidth] = useState(700);
    useEffect(() => {
        const element = ref.current;
        if (!element) return;
        const observer = new IntersectionObserver(
            ([entry]) => setVisible(entry.isIntersecting),
            { root: element.closest(".reading-scroll"), rootMargin: "800px" },
        );
        const resize = new ResizeObserver(([entry]) =>
            setAvailableWidth(entry.contentRect.width),
        );
        observer.observe(element);
        resize.observe(element);
        return () => {
            observer.disconnect();
            resize.disconnect();
        };
    }, []);
    return (
        <section
            ref={ref}
            data-reader-page={page - 1}
            className="continuous-pdf-page"
            style={{
                minHeight:
                    Math.max(0.2, (availableWidth - 48) / width) *
                        height *
                        zoom +
                    48,
            }}
        >
            {visible && (
                <PdfPage
                    document={document}
                    page={page}
                    zoom={zoom}
                    annotations={annotations}
                    onReady={() => {}}
                    onSelection={(rectangles) =>
                        onSelection(page - 1, rectangles)
                    }
                />
            )}
        </section>
    );
}

export function PdfDocument({
    assetId,
    pages,
    zoom,
    annotations,
    onOutline,
    onReady,
    onSelection,
}: {
    assetId: string;
    pages: Span[];
    zoom: number;
    annotations: Annotation[];
    onOutline: (items: OutlineItem[]) => void;
    onReady: () => void;
    onSelection: (page: number, rectangles: number[][]) => void;
}) {
    const [document, setDocument] = useState<PDFDocumentProxy | null>(null),
        [sizes, setSizes] = useState<{ width: number; height: number }[]>([]),
        [error, setError] = useState("");
    const callbacks = useRef({ onOutline, onReady });
    callbacks.current = { onOutline, onReady };
    useEffect(() => {
        let live = true;
        const task = getDocument({
            url: `/api/assets/${assetId}?inline=true`,
            useSystemFonts: true,
        });
        setDocument(null);
        setSizes([]);
        setError("");
        void task.promise
            .then(async (doc) => {
                const sizes = await Promise.all(
                    Array.from({ length: doc.numPages }, async (_, i) => {
                        const page = await doc.getPage(i + 1),
                            viewport = page.getViewport({ scale: 1 });
                        return {
                            width: viewport.width,
                            height: viewport.height,
                        };
                    }),
                );
                const items: OutlineItem[] = [];
                const outline = await doc.getOutline();
                async function collect(
                    nodes: NonNullable<typeof outline>,
                    depth: number,
                ) {
                    for (const node of nodes) {
                        const dest =
                            typeof node.dest === "string"
                                ? await doc.getDestination(node.dest)
                                : node.dest;
                        if (Array.isArray(dest) && dest.length) {
                            const index =
                                typeof dest[0] === "number"
                                    ? dest[0]
                                    : await doc.getPageIndex(dest[0]);
                            items.push({
                                title: node.title,
                                page: index + 1,
                                depth,
                            });
                        }
                        if (node.items?.length)
                            await collect(node.items, depth + 1);
                    }
                }
                if (outline) await collect(outline, 0);
                if (live) {
                    setDocument(doc);
                    setSizes(sizes);
                    callbacks.current.onOutline(items);
                }
            })
            .catch((error) => {
                if (live) setError(error.message);
            });
        return () => {
            live = false;
            void task.destroy();
        };
    }, [assetId]);
    useEffect(() => {
        if (document && sizes.length) {
            let frame = requestAnimationFrame(() => {
                frame = requestAnimationFrame(() =>
                    callbacks.current.onReady(),
                );
            });
            return () => cancelAnimationFrame(frame);
        }
    }, [document, sizes.length]);
    if (error) return <p className="error-text">{error}</p>;
    if (!document) return <Spinner />;
    return (
        <div className="reader-pdf-flow">
            {sizes.map((size, i) => (
                <VisiblePage
                    key={i}
                    document={document}
                    page={i + 1}
                    {...size}
                    zoom={zoom}
                    annotations={annotations.filter(
                        (item) => item.source_span_id === pages[i]?.id,
                    )}
                    onSelection={onSelection}
                />
            ))}
        </div>
    );
}
