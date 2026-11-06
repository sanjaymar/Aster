import {
    ArrowLeft,
    Check,
    Clock,
    Download,
    Eye,
    PanelRightOpen,
    Printer,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
    api,
    send,
    type Asset,
    type RecordItem,
    type Version,
    type Source,
} from "../../shared/api";
import { AttachmentPicker } from "../../shared/Attachments";
import { MarkdownView } from "../../shared/MarkdownView";
import { Modal, Spinner, date, kindLabels } from "../../shared/ui";
import { RichTextEditor } from "./RichTextEditor";
import { DeleteButton } from "../../shared/DeleteButton";
import { DocumentProperties, type NoteProperties } from "./DocumentProperties";
import { templates, noteTypes } from "./templates";

type Draft = NoteProperties & {
    title: string;
    content: string;
    confirmed: boolean;
    folder: string;
    assets: Asset[];
};
export function DocumentEditor({
    projectId,
    record,
    kind,
    initialContent = "",
    initialTitle = "",
    initialFields = {},
    sources = [],
    records = [],
    onSaved,
    onEvidence,
    onClose,
    onError,
    onCsv,
}: {
    projectId: string;
    record?: RecordItem;
    kind: string;
    initialContent?: string;
    initialTitle?: string;
    initialFields?: Record<string, unknown>;
    sources?: Source[];
    records?: RecordItem[];
    onSaved: () => void;
    onEvidence: (kind: string, id: string) => void;
    onClose: () => void;
    onError: (message: string) => void;
    onCsv: (asset: Asset) => void;
}) {
    const fields = record?.version.fields || initialFields;
    const initial: Draft = {
        title: record?.title || initialTitle,
        content: record?.version.content || initialContent,
        confirmed: record?.status === "confirmed",
        folder: String(fields.folder || ""),
        assets: record?.attachments || [],
        noteType: String(
            fields.note_type || (fields.source_id ? "reading" : "note"),
        ),
        tags: Array.isArray(fields.tags) ? fields.tags.join(", ") : "",
        pinned: !!fields.pinned,
        sourceId: String(fields.source_id || ""),
        relatedIds: Array.isArray(fields.related_record_ids)
            ? fields.related_record_ids.map(String)
            : [],
    };
    const draftKey = `aster:draft:${projectId}:${record?.id || `new-${kind}`}`;
    const [draft, setDraft] = useState<Draft>(() => {
        try {
            const cached = JSON.parse(localStorage.getItem(draftKey) || "null");
            if (cached && cached.base_revision === (record?.revision || 0))
                return { ...initial, ...cached.draft };
        } catch {
            /* ignore invalid browser cache */
        }
        return initial;
    });
    const [revision, setRevision] = useState(record?.revision || 0),
        [saving, setSaving] = useState(false),
        [saved, setSaved] = useState(false),
        [error, setError] = useState(""),
        [preview, setPreview] = useState(fields.layout === "report"),
        [history, setHistory] = useState<Version[] | null>(null),
        [historical, setHistorical] = useState<Version | null>(null);
    const [properties, setProperties] = useState(false);
    const sheet = useRef<HTMLDivElement>(null);
    const titleInput = useRef<HTMLTextAreaElement>(null);
    useEffect(() => {
        const resize = () => {
            const input = titleInput.current;
            if (input) {
                input.style.height = "auto";
                input.style.height = `${input.scrollHeight}px`;
            }
        };
        resize();
        window.addEventListener("resize", resize);
        return () => window.removeEventListener("resize", resize);
    }, [draft.title]);
    const latest = useRef(draft);
    latest.current = draft;
    const persisted = useRef(JSON.stringify(initial)),
        id = useRef(record?.id),
        rev = useRef(record?.revision || 0),
        savingPromise = useRef<Promise<void> | null>(null),
        paused = useRef(false);
    const callbacks = useRef({ onSaved, onError });
    callbacks.current = { onSaved, onError };
    const dirty = JSON.stringify(draft) !== persisted.current;
    useEffect(() => {
        try {
            if (dirty)
                localStorage.setItem(
                    draftKey,
                    JSON.stringify({ base_revision: rev.current, draft }),
                );
        } catch {
            setError("浏览器草稿空间不足，请手动保存");
        }
    }, [draft, dirty, draftKey]);
    useEffect(() => {
        const warn = (event: BeforeUnloadEvent) => {
            if (JSON.stringify(latest.current) !== persisted.current)
                event.preventDefault();
        };
        window.addEventListener("beforeunload", warn);
        return () => window.removeEventListener("beforeunload", warn);
    }, []);
    const save = useCallback(async (): Promise<void> => {
        if (savingPromise.current) {
            await savingPromise.current;
            if (JSON.stringify(latest.current) !== persisted.current)
                return save();
            return;
        }
        const current = latest.current,
            snapshot = JSON.stringify(current);
        if (
            snapshot === persisted.current ||
            (!current.title.trim() && !current.content.trim())
        )
            return;
        const operation = (async () => {
            setSaving(true);
            setError("");
            try {
                const row = await api<RecordItem>(
                    `/projects/${projectId}/artifacts${id.current ? `/${id.current}` : ""}`,
                    send(id.current ? "PUT" : "POST", {
                        title:
                            current.title.trim() ||
                            `未命名${kindLabels[kind] || "文档"}`,
                        kind,
                        content: current.content,
                        fields: {
                            ...fields,
                            folder: current.folder,
                            note_type: current.noteType,
                            tags: [
                                ...new Set(
                                    current.tags
                                        .split(/[,，]/)
                                        .map((t) => t.trim())
                                        .filter(Boolean),
                                ),
                            ].slice(0, 12),
                            pinned: current.pinned,
                            source_id: current.sourceId,
                            related_record_ids: current.relatedIds,
                        },
                        status: current.confirmed ? "confirmed" : "draft",
                        asset_ids: current.assets.map((asset) => asset.id),
                        ...(id.current
                            ? { expected_revision: rev.current }
                            : {}),
                    }),
                );
                id.current = row.id;
                rev.current = row.revision;
                persisted.current = snapshot;
                paused.current = false;
                setRevision(row.revision);
                setSaved(true);
                if (JSON.stringify(latest.current) === snapshot)
                    localStorage.removeItem(draftKey);
                callbacks.current.onSaved();
            } catch (error) {
                paused.current = true;
                setError((error as Error).message);
                callbacks.current.onError((error as Error).message);
                throw error;
            } finally {
                setSaving(false);
            }
        })();
        savingPromise.current = operation;
        try {
            await operation;
        } finally {
            savingPromise.current = null;
        }
    }, [projectId, kind, draftKey]);
    useEffect(() => {
        const hotkey = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
                e.preventDefault();
                void save().catch(() => {});
            }
        };
        window.addEventListener("keydown", hotkey);
        return () => window.removeEventListener("keydown", hotkey);
    }, [save]);
    useEffect(() => {
        if (!dirty || paused.current || saving) return;
        const timer = setTimeout(() => {
            void save().catch(() => {});
        }, 2500);
        return () => clearTimeout(timer);
    }, [draft, dirty, saving, save]);
    async function close() {
        try {
            await save();
            onClose();
        } catch {
            /* retain open editor and browser draft */
        }
    }
    function download() {
        const blob = new Blob([`# ${draft.title}\n\n${draft.content}`], {
            type: "text/markdown;charset=utf-8",
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${draft.title.replace(/[\\/:*?"<>|]/g, "_") || "document"}.md`;
        link.click();
        URL.revokeObjectURL(url);
    }
    return (
        <section className="document-workspace">
            <header className="document-topline">
                <button className="text-button" onClick={() => void close()}>
                    <ArrowLeft size={15} />
                    返回
                </button>
                <span className="document-save-state">
                    {saving ? (
                        <>
                            <Spinner />
                            保存中
                        </>
                    ) : dirty ? (
                        "未保存"
                    ) : saved || revision ? (
                        <>
                            <Check size={13} />
                            已保存 · v{revision}
                        </>
                    ) : (
                        "新文档"
                    )}
                </span>
                <span className="toolbar-spacer" />
                <select
                    aria-label="插入文档模板"
                    className="insert-template"
                    value=""
                    onChange={(e) => {
                        const template = templates.find(
                            (t) => t.id === e.target.value,
                        );
                        if (template)
                            setDraft((current) => ({
                                ...current,
                                content:
                                    current.content +
                                    (current.content ? "\n\n" : "") +
                                    template.content,
                                noteType: current.content
                                    ? current.noteType
                                    : template.type,
                            }));
                    }}
                >
                    <option value="">插入模板</option>
                    {templates
                        .filter((t) => t.content)
                        .map((t) => (
                            <option key={t.id} value={t.id}>
                                {t.label}
                            </option>
                        ))}
                </select>
                <button
                    className="text-button"
                    aria-label="文档属性"
                    onClick={() => setProperties((v) => !v)}
                >
                    <PanelRightOpen size={15} />
                    属性
                </button>
                {id.current && (
                    <DeleteButton
                        path={`/projects/${projectId}/artifacts/${id.current}`}
                        title={draft.title}
                        label="删除文档"
                        beforeDelete={async () => {
                            await save();
                            paused.current = true;
                        }}
                        onDeleted={() => {
                            onSaved();
                            onClose();
                        }}
                        onError={onError}
                    />
                )}
                {id.current && (
                    <button
                        className="text-button"
                        onClick={() =>
                            api<{ versions: Version[] }>(
                                `/projects/${projectId}/artifacts/${id.current}/history`,
                            )
                                .then((data) => setHistory(data.versions))
                                .catch((error) => onError(error.message))
                        }
                    >
                        <Clock size={14} />
                        历史版本
                    </button>
                )}
                <button className="text-button" onClick={download}>
                    <Download size={14} />
                    导出
                </button>
                <button
                    className="text-button"
                    onClick={() => {
                        setPreview(true);
                        setTimeout(() => window.print(), 150);
                    }}
                >
                    <Printer size={14} />
                    PDF
                </button>
                <button
                    className="text-button"
                    onClick={() => setPreview((v) => !v)}
                >
                    <Eye size={14} />
                    {preview ? "编辑" : "预览"}
                </button>
                <button
                    className="button primary"
                    disabled={
                        saving || (!draft.title.trim() && !draft.content.trim())
                    }
                    onClick={() => void save().catch(() => {})}
                >
                    保存
                </button>
            </header>
            {error && (
                <div className="error-banner">
                    {error}。当前修改已保留在浏览器草稿中。
                </div>
            )}
            <div
                className={`document-body ${properties ? "with-properties" : ""}`}
            >
                <nav className="document-outline" aria-label="文档目录">
                    {draft.content
                        .match(/^#{1,3} .+$/gm)
                        ?.slice(0, 16)
                        .map((line, index) => (
                            <button
                                key={index}
                                style={{
                                    paddingLeft:
                                        10 +
                                        (line.match(/^#+/)?.[0].length || 1) *
                                            6,
                                }}
                                onClick={() => {
                                    const heading = [
                                        ...(sheet.current?.querySelectorAll(
                                            "h1,h2,h3",
                                        ) || []),
                                    ].find(
                                        (el) =>
                                            el.textContent ===
                                            line.replace(/^#+ /, ""),
                                    );
                                    heading?.scrollIntoView({
                                        behavior: "smooth",
                                        block: "center",
                                    });
                                }}
                            >
                                {line.replace(/^#+ /, "")}
                            </button>
                        ))}
                </nav>
                <div
                    className={`document-sheet ${draft.noteType === "reading" || fields.layout === "report" ? "reading-report" : ""}`}
                    ref={sheet}
                    data-layout={
                        fields.layout === "report" ? "report" : undefined
                    }
                >
                    {(draft.noteType === "reading" ||
                        fields.layout === "report") && (
                        <div className="report-eyebrow">
                            READING NOTES{" "}
                            <span>
                                {fields.origin === "generated"
                                    ? "自动生成 · 可编辑"
                                    : "手动记录"}
                            </span>
                        </div>
                    )}
                    <textarea
                        ref={titleInput}
                        className="document-title"
                        rows={2}
                        aria-label="标题"
                        placeholder="未命名文档"
                        value={draft.title}
                        onChange={(e) =>
                            setDraft({ ...draft, title: e.target.value })
                        }
                        maxLength={300}
                    />
                    <h1 className="document-print-title">{draft.title}</h1>
                    <div className="document-meta">
                        <span>
                            {noteTypes[draft.noteType] ||
                                kindLabels[kind] ||
                                "文档"}
                        </span>
                        <input
                            aria-label="文档分类"
                            placeholder="分类"
                            value={draft.folder}
                            maxLength={80}
                            onChange={(e) =>
                                setDraft({ ...draft, folder: e.target.value })
                            }
                        />
                        <label className="check-label">
                            <input
                                type="checkbox"
                                checked={draft.confirmed}
                                onChange={(e) =>
                                    setDraft({
                                        ...draft,
                                        confirmed: e.target.checked,
                                    })
                                }
                            />
                            已核对
                        </label>
                        <span>
                            {
                                draft.content.replace(/\[\[[^\]]+\]\]/g, "")
                                    .length
                            }{" "}
                            字符
                        </span>
                    </div>
                    {preview ? (
                        <MarkdownView
                            text={draft.content}
                            onEvidence={onEvidence}
                        />
                    ) : (
                        <RichTextEditor
                            value={draft.content}
                            onChange={(content) =>
                                setDraft((current) => ({ ...current, content }))
                            }
                        />
                    )}
                    <AttachmentPicker
                        projectId={projectId}
                        items={draft.assets}
                        onChange={(assets) =>
                            setDraft((current) => ({ ...current, assets }))
                        }
                        onError={onError}
                        onCsv={onCsv}
                    />
                </div>
                {properties && (
                    <DocumentProperties
                        value={draft}
                        sources={sources}
                        records={records}
                        id={id.current}
                        onChange={(value) =>
                            setDraft((current) => ({ ...current, ...value }))
                        }
                        onReference={(r) =>
                            setDraft((current) => ({
                                ...current,
                                content:
                                    current.content +
                                    `\n\n[[V:${r.version.id}]]\n`,
                            }))
                        }
                    />
                )}
            </div>
            {history && (
                <Modal
                    title="历史版本"
                    onClose={() => {
                        setHistory(null);
                        setHistorical(null);
                    }}
                    wide
                >
                    <div className="version-picker">
                        {history.map((version) => (
                            <button
                                className="chip"
                                key={version.id}
                                onClick={() => setHistorical(version)}
                            >
                                v{version.number} · {date(version.created_at)}
                            </button>
                        ))}
                    </div>
                    {historical && (
                        <>
                            <MarkdownView
                                text={historical.content}
                                onEvidence={onEvidence}
                            />
                            <button
                                className="button secondary"
                                onClick={() => {
                                    setDraft((current) => ({
                                        ...current,
                                        content: historical.content,
                                    }));
                                    setHistory(null);
                                    setHistorical(null);
                                }}
                            >
                                恢复内容为新版本
                            </button>
                        </>
                    )}
                </Modal>
            )}
        </section>
    );
}
