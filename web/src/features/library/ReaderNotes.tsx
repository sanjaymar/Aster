import { FileText, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { api, send, type RecordItem, type Source } from "../../shared/api";
import { Spinner, date } from "../../shared/ui";
import { RichTextEditor } from "../documents/RichTextEditor";

export function ReaderNotes({
    projectId,
    source,
    notes,
    seed,
    onOpen,
    onSaved,
    onError,
}: {
    projectId: string;
    source: Source;
    notes: RecordItem[];
    seed?: { text: string; key: number };
    onOpen: (note: RecordItem) => void;
    onSaved: () => void;
    onError: (message: string) => void;
}) {
    const cacheKey = `aster:reader-note:${projectId}:${source.id}`;
    const [draft, setDraft] = useState<{
            title: string;
            content: string;
        } | null>(() => {
            try {
                return JSON.parse(localStorage.getItem(cacheKey) || "null");
            } catch {
                return null;
            }
        }),
        [busy, setBusy] = useState(false);
    useEffect(() => {
        if (seed)
            setDraft((current) => ({
                title: current?.title || `${source.title.slice(0, 60)} · 笔记`,
                content: current?.content
                    ? `${current.content}\n\n${seed.text}`
                    : seed.text,
            }));
    }, [seed?.key]);
    useEffect(() => {
        try {
            if (draft) localStorage.setItem(cacheKey, JSON.stringify(draft));
            else localStorage.removeItem(cacheKey);
        } catch {
            /* server save remains available */
        }
    }, [draft, cacheKey]);
    async function save() {
        if (!draft || busy) return;
        setBusy(true);
        try {
            await api(
                `/projects/${projectId}/artifacts`,
                send("POST", {
                    title: draft.title || "阅读笔记",
                    kind: "note",
                    content: draft.content,
                    fields: { source_id: source.id },
                    status: "draft",
                }),
            );
            setDraft(null);
            onSaved();
        } catch (error) {
            onError((error as Error).message);
        } finally {
            setBusy(false);
        }
    }
    return (
        <div className="reader-notes">
            <div className="section-heading">
                <span>{notes.length} 篇笔记</span>
                <button
                    className="text-button"
                    onClick={() =>
                        setDraft(
                            (current) =>
                                current || {
                                    title: `${source.title.slice(0, 60)} · 笔记`,
                                    content: "",
                                },
                        )
                    }
                >
                    <Plus size={14} />
                    新建
                </button>
            </div>
            {draft && (
                <div className="reader-note-draft">
                    <input
                        aria-label="阅读笔记标题"
                        value={draft.title}
                        onChange={(e) =>
                            setDraft({ ...draft, title: e.target.value })
                        }
                        maxLength={300}
                    />
                    <RichTextEditor
                        compact
                        label="阅读笔记正文"
                        value={draft.content}
                        onChange={(content) =>
                            setDraft((current) =>
                                current ? { ...current, content } : null,
                            )
                        }
                    />
                    <div className="inline spread">
                        <span className="muted small">浏览器草稿</span>
                        <button
                            className="button primary"
                            disabled={busy || !draft.content.trim()}
                            onClick={() => void save()}
                        >
                            {busy ? <Spinner /> : null}保存笔记
                        </button>
                    </div>
                </div>
            )}
            {notes.map((note) => (
                <button
                    className="reader-linked-note"
                    key={note.id}
                    onClick={() => onOpen(note)}
                >
                    <FileText size={15} />
                    <span>
                        <strong>{note.title}</strong>
                        <small>
                            {date(note.updated_at)} · v{note.revision}
                        </small>
                        <p>
                            {note.version.content
                                .replace(/\[\[[^\]]+\]\]/g, "")
                                .slice(0, 100)}
                        </p>
                    </span>
                </button>
            ))}
            {!notes.length && !draft && <p className="plain-empty">暂无笔记</p>}
        </div>
    );
}
