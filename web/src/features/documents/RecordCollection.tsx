import { Feather, NotebookPen, Plus, Pin } from "lucide-react";
import { noteTypes } from "./templates";
import { type RecordItem } from "../../shared/api";
import { Empty, date, kindLabels } from "../../shared/components";

function excerpt(record: RecordItem) {
    const body = record.version.content;
    const summary =
        body.match(/## 核心要点\s+([\s\S]*?)(?=\n## |$)/)?.[1] || body;
    return (
        summary
            .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
            .replace(/\[\[[^\]]+\]\]/g, "")
            .replace(/[#*>`|]/g, "")
            .replace(/\s+/g, " ")
            .trim()
            .slice(0, 190) || "还没有正文"
    );
}

export function RecordCollection({
    items,
    selected,
    onToggle,
    onOpen,
    kind,
    onNew,
    view = "grid",
}: {
    items: RecordItem[];
    selected: string[];
    onToggle: (id: string) => void;
    onOpen: (r: RecordItem) => void;
    kind: string;
    onNew: () => void;
    view?: "grid" | "list";
}) {
    return items.length ? (
        <div className={view === "list" ? "note-list" : "note-grid"}>
            {items.map((a) => (
                <article
                    className={`note-card ${a.version.fields.layout === "report" ? "report-card" : ""}`}
                    key={a.id}
                >
                    <div className="inline spread">
                        <span
                            className={
                                "badge " +
                                (a.status === "confirmed" ? "confirmed" : "")
                            }
                        >
                            {a.status === "confirmed"
                                ? "已核对"
                                : a.version.author === "assistant"
                                  ? "助手草稿"
                                  : "草稿"}
                        </span>
                        <input
                            type="checkbox"
                            aria-label={"选择记录 " + a.title}
                            checked={selected.includes(a.id)}
                            onChange={() => onToggle(a.id)}
                        />
                    </div>
                    <button className="note-open" onClick={() => onOpen(a)}>
                        <h3>
                            {!!a.version.fields.pinned && <Pin size={13} />}{" "}
                            {a.title}
                        </h3>
                        <p>{excerpt(a)}</p>
                    </button>
                    {Array.isArray(a.version.fields.tags) && (
                        <div className="note-tags">
                            {a.version.fields.tags
                                .slice(0, 4)
                                .map((t: unknown) => (
                                    <span key={String(t)}>#{String(t)}</span>
                                ))}
                        </div>
                    )}
                    <div className="note-meta">
                        <span>
                            {noteTypes[String(a.version.fields.note_type)] ||
                                kindLabels[a.kind] ||
                                a.kind}{" "}
                            · v{a.revision}
                        </span>
                        <span>{date(a.updated_at)}</span>
                    </div>
                </article>
            ))}
        </div>
    ) : (
        <Empty
            icon={
                kind === "draft" ? (
                    <Feather size={30} />
                ) : (
                    <NotebookPen size={30} />
                )
            }
            title="暂无文档"
            action={
                <button className="button secondary" onClick={onNew}>
                    <Plus size={15} />
                    新建{kind === "draft" ? "草稿" : "笔记"}
                </button>
            }
        ></Empty>
    );
}
