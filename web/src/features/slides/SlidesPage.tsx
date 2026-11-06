import { useState } from "react";
import { Plus, Presentation, ArrowUpRight } from "lucide-react";
import { api, send, type Bundle, type RecordItem } from "../../shared/api";
import {
    AssistantOptions,
    useAssistantOptions,
} from "../assistant/AssistantOptions";
import type { ResearchTask } from "../workspace/Home";
import { Spinner } from "../../shared/ui";
import { Materials } from "./Materials";

export type Slide = {
    title: string;
    bullets: string[];
    notes: string;
    citations: string[];
    image_asset_id?: string | null;
    layout?:
        | "cover"
        | "bullets"
        | "flow"
        | "table"
        | "figure"
        | "comparison"
        | "closing";
    subtitle?: string;
    takeaway?: string;
    image_caption?: string;
    steps?: { label: string; detail: string }[];
    table?: { headers: string[]; rows: string[][] };
};
export type Deck = {
    title: string;
    theme: "academic" | "paper" | "ink";
    slides: Slide[];
};
export function SlidesPage({
    projectId,
    bundle,
    initialSources = [],
    onOpen,
    onStart,
    onError,
    onRefresh,
}: {
    projectId: string;
    bundle: Bundle;
    initialSources?: string[];
    onOpen: (r: RecordItem) => void;
    onStart: (t: ResearchTask) => Promise<void>;
    onError: (m: string) => void;
    onRefresh: () => void;
}) {
    const [prompt, setPrompt] = useState(""),
        [sources, setSources] = useState<string[]>(initialSources),
        [notes, setNotes] = useState<string[]>([]),
        [busy, setBusy] = useState(false);
    const options = useAssistantOptions(false);
    async function blank() {
        try {
            const r = await api<RecordItem>(
                `/projects/${projectId}/decks`,
                send("POST", {
                    title: "新的汇报",
                    theme: "academic",
                    slides: [
                        {
                            title: "研究问题",
                            bullets: [],
                            notes: "",
                            citations: [],
                        },
                    ],
                }),
            );
            onRefresh();
            onOpen(r);
        } catch (e) {
            onError((e as Error).message);
        }
    }
    async function generate() {
        setBusy(true);
        try {
            await onStart({
                prompt:
                    prompt ||
                    "根据所选论文和笔记制作8到12页学术蓝白风格组会汇报，包含方法流程、原文图解与结果对照，保留引用和讲稿。",
                mode: "slides",
                scope: "selected",
                responseStyle: "grounded",
                sourceIds: sources,
                artifactIds: notes,
                skillId: options.skillId || "research-slides",
                modelId: options.modelId,
            });
        } catch (e) {
            onError((e as Error).message);
        } finally {
            setBusy(false);
        }
    }
    return (
        <div className="slides-page">
            <div className="page-heading">
                <h1>
                    汇报{" "}
                    <small className="heading-count">
                        {bundle.records.filter((r) => r.kind === "deck").length}
                    </small>
                </h1>
                <button className="button secondary" onClick={blank}>
                    <Plus size={15} />
                    空白汇报
                </button>
            </div>
            <section className="deck-create">
                <div>
                    <h2>从论文与笔记开始</h2>
                    <textarea
                        aria-label="汇报要求"
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        placeholder="汇报主题、页数、听众…"
                        maxLength={4000}
                    />
                    <AssistantOptions
                        options={options}
                        reader={false}
                        disabled={busy}
                    />
                </div>
                <div className="deck-materials">
                    <Materials
                        label="论文"
                        items={bundle.sources}
                        selected={sources}
                        limit={10}
                        onChange={setSources}
                    />
                    <Materials
                        label="笔记"
                        items={bundle.records.filter((r) => r.kind === "note")}
                        selected={notes}
                        limit={20}
                        onChange={setNotes}
                    />
                    <button
                        className="button primary"
                        disabled={busy || (!sources.length && !notes.length)}
                        onClick={generate}
                    >
                        {busy ? <Spinner /> : <Presentation size={16} />}
                        生成汇报提纲
                    </button>
                </div>
            </section>
            <div className="deck-grid">
                {bundle.records
                    .filter((r) => r.kind === "deck")
                    .map((r) => (
                        <button
                            className="deck-card"
                            key={r.id}
                            onClick={() => onOpen(r)}
                        >
                            <div className="deck-cover">
                                <span>ASTER / PRESENTATION</span>
                                <strong>{r.title}</strong>
                                <ArrowUpRight size={18} />
                            </div>
                            <small>
                                {(r.version.fields.deck as Deck)?.slides
                                    ?.length || 0}{" "}
                                页 · 可编辑
                            </small>
                        </button>
                    ))}
            </div>
        </div>
    );
}
