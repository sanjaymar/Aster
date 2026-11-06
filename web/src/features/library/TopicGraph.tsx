import { useEffect, useRef } from "react";
import cytoscape, { type Core } from "cytoscape";
import { Minus, Plus, Maximize2 } from "lucide-react";
export type MapNode = {
    id: string;
    title: string;
    authors: string;
    abstract: string;
    journal: string;
    year: string;
    topic: string;
    color: string;
    keywords: string[];
    tags: string[];
    notes: { id: string; title: string }[];
    reading_status: string;
    x: number;
    y: number;
};
export type MapData = {
    nodes: MapNode[];
    edges: { source: string; target: string; score: number }[];
    topics: {
        id: string;
        label: string;
        keywords: string[];
        color: string;
        count: number;
    }[];
    stats: { papers: number; topics: number; notes: number; read: number };
};
export function TopicGraph({
    data,
    visible,
    focus,
    onSelect,
}: {
    data: MapData;
    visible: string[];
    focus: string;
    onSelect: (id: string) => void;
}) {
    const container = useRef<HTMLDivElement>(null),
        graph = useRef<Core | undefined>(undefined);
    const handler = useRef(onSelect);
    handler.current = onSelect;
    const visibleKey = visible.join(",");
    useEffect(() => {
        if (!container.current) return;
        const ids = new Set(visible),
            nodes = data.nodes.filter((n) => ids.has(n.id)),
            topics = data.topics.filter((t) =>
                nodes.some((n) => n.topic === t.id),
            );
        const cy = cytoscape({
            container: container.current,
            layout: { name: "preset", padding: 45 },
            minZoom: 0.15,
            maxZoom: 5,
            wheelSensitivity: 0.25,
            elements: [
                ...topics.map((t) => ({
                    data: { id: t.id, label: t.label, color: t.color },
                    classes: "topic",
                })),
                ...nodes.map((n) => ({
                    data: {
                        id: n.id,
                        parent: n.topic,
                        title: n.title,
                        label:
                            n.title.length > 50
                                ? n.title.slice(0, 48) + "…"
                                : n.title,
                        color: n.color,
                        size: n.notes.length ? 15 : 10,
                    },
                    position: { x: n.x, y: n.y },
                })),
                ...data.edges
                    .filter((e) => ids.has(e.source) && ids.has(e.target))
                    .map((e, i) => ({
                        data: {
                            id: `edge-${i}`,
                            source: e.source,
                            target: e.target,
                        },
                    })),
            ],
            style: [
                {
                    selector: "node",
                    style: {
                        "background-color": "data(color)",
                        width: "data(size)",
                        height: "data(size)",
                        "border-width": 2,
                        "border-color": "#fff",
                        label: "",
                        "font-size": 10,
                        "text-wrap": "wrap",
                        "text-max-width": "130px",
                        color: "#353840",
                        "text-margin-y": 8,
                        "text-valign": "bottom",
                    },
                },
                {
                    selector: "node.topic",
                    style: {
                        "background-color": "data(color)",
                        "background-opacity": 0.035,
                        "border-color": "data(color)",
                        "border-opacity": 0.16,
                        "border-width": 1,
                        shape: "round-rectangle",
                        label: "data(label)",
                        "text-valign": "top",
                        "text-margin-y": -12,
                        "font-weight": "bold",
                        "font-size": 16,
                        color: "data(color)",
                        padding: "30px",
                    },
                },
                {
                    selector: "edge",
                    style: {
                        width: 0.7,
                        "line-color": "#b6bdc9",
                        opacity: 0.2,
                        "curve-style": "bezier",
                    },
                },
                {
                    selector: "node.highlight",
                    style: {
                        label: "data(label)",
                        "border-color": "#202124",
                        "border-width": 2,
                        width: 18,
                        height: 18,
                        "z-index": 10,
                    },
                },
                {
                    selector: "node.neighbor",
                    style: {
                        label: "data(label)",
                        width: 14,
                        height: 14,
                        "z-index": 9,
                    },
                },
                {
                    selector: "edge.highlight",
                    style: {
                        width: 1.8,
                        "line-color": "#536f99",
                        opacity: 0.8,
                    },
                },
                { selector: ".dim", style: { opacity: 0.15 } },
            ],
        });
        graph.current = cy;
        cy.on("tap", "node:not(.topic)", (event) =>
            handler.current(event.target.id()),
        );
        cy.on("tap", (event) => {
            if (event.target === cy) handler.current("");
        });
        cy.on("mouseover", "node:not(.topic)", (event) => {
            event.target.addClass("neighbor");
            if (container.current) container.current.style.cursor = "pointer";
        });
        cy.on("mouseout", "node:not(.topic)", (event) => {
            if (!event.target.hasClass("highlight"))
                event.target.removeClass("neighbor");
            if (container.current) container.current.style.cursor = "grab";
        });
        const observer = new ResizeObserver(() => {
            cy.resize();
        });
        observer.observe(container.current);
        return () => {
            observer.disconnect();
            cy.destroy();
        };
    }, [data, visibleKey]);
    useEffect(() => {
        const cy = graph.current;
        if (!cy) return;
        cy.elements().removeClass("highlight neighbor dim");
        if (focus && cy.getElementById(focus).length) {
            const node = cy.getElementById(focus),
                neighbors = node.closedNeighborhood();
            cy.elements().not(neighbors).not(".topic").addClass("dim");
            node.addClass("highlight");
            neighbors.edges().addClass("highlight");
            neighbors.nodes().not(node).addClass("neighbor");
        }
    }, [focus, data, visibleKey]);
    function zoom(factor: number) {
        const cy = graph.current;
        if (cy)
            cy.zoom({
                level: cy.zoom() * factor,
                renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
            });
    }
    return (
        <div className="topic-graph">
            <div
                ref={container}
                className="topic-canvas"
                aria-label="交互式文献主题图"
            />
            <div className="topic-controls">
                <button aria-label="缩小地图" onClick={() => zoom(0.8)}>
                    <Minus size={15} />
                </button>
                <button aria-label="放大地图" onClick={() => zoom(1.25)}>
                    <Plus size={15} />
                </button>
                <button
                    aria-label="适应画布"
                    onClick={() => graph.current?.fit(undefined, 45)}
                >
                    <Maximize2 size={15} />
                </button>
            </div>
        </div>
    );
}
