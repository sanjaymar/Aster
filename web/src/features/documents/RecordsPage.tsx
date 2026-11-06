import { Folder, Plus, Search, LayoutGrid, List } from "lucide-react";
import {
    useEffect,
    useMemo,
    useState,
    type Dispatch,
    type SetStateAction,
} from "react";
import type { Bundle, Project, RecordItem } from "../../shared/api";
import type { EditorState } from "../../shared/types";
import { RecordCollection } from "./RecordCollection";
import { templates, noteTypes } from "./templates";
export function RecordsPage({
    page,
    project,
    bundle,
    artifactIds,
    setArtifactIds,
    setEditor,
    openRecord,
}: {
    page: string;
    project: Project;
    bundle: Bundle;
    artifactIds: string[];
    setArtifactIds: Dispatch<SetStateAction<string[]>>;
    setEditor: Dispatch<SetStateAction<EditorState | null>>;
    openRecord: (record: RecordItem) => void;
}) {
    const [query, setQuery] = useState(""),
        [folder, setFolder] = useState(""),
        [template, setTemplate] = useState(""),
        [type, setType] = useState(""),
        [tag, setTag] = useState(""),
        [view, setView] = useState<"grid" | "list">("grid");
    useEffect(() => {
        setQuery("");
        setFolder("");
        setTemplate("");
        setType("");
        setTag("");
    }, [page]);
    const records = bundle.records.filter((record) =>
        page === "notes"
            ? record.kind === "note"
            : ["draft", "report"].includes(record.kind),
    );
    const folders = [
        ...new Set(
            records
                .map((record) => String(record.version.fields.folder || ""))
                .filter(Boolean),
        ),
    ].sort();
    const items = useMemo(
        () =>
            records
                .filter(
                    (record) =>
                        (!folder || record.version.fields.folder === folder) &&
                        (!type || record.version.fields.note_type === type) &&
                        (!tag ||
                            (Array.isArray(record.version.fields.tags) &&
                                record.version.fields.tags.includes(tag))) &&
                        `${record.title} ${record.version.content} ${JSON.stringify(record.version.fields.tags || [])}`
                            .toLocaleLowerCase()
                            .includes(query.toLocaleLowerCase()),
                )
                .sort(
                    (a, b) =>
                        Number(!!b.version.fields.pinned) -
                            Number(!!a.version.fields.pinned) ||
                        b.updated_at.localeCompare(a.updated_at),
                ),
        [records, query, folder, type, tag],
    );
    function create() {
        const selected = templates.find((t) => t.id === template);
        setEditor({
            kind: page === "notes" ? "note" : "draft",
            content: selected?.content || "",
            fields: {
                note_type:
                    selected?.type || (page === "notes" ? "note" : "writing"),
                folder,
            },
        });
    }
    return (
        <>
            <div className="page-heading">
                <h1>
                    {page === "notes"
                        ? "笔记"
                        : project.domain === "general"
                          ? "写作"
                          : "论文写作"}
                    <small className="heading-count">{records.length}</small>
                </h1>
                <div className="inline">
                    <select
                        aria-label="新建文档模板"
                        value={template}
                        onChange={(e) => setTemplate(e.target.value)}
                    >
                        <option value="">空白文档</option>
                        {templates
                            .filter((t) =>
                                page === "notes"
                                    ? t.type !== "writing" && t.id !== "labnote"
                                    : t.type === "writing",
                            )
                            .map((item) => (
                                <option key={item.id} value={item.id}>
                                    {item.label}
                                </option>
                            ))}
                    </select>
                    <button className="button primary" onClick={create}>
                        <Plus size={15} />
                        {page === "notes" ? "新建笔记" : "新建文档"}
                    </button>
                </div>
            </div>
            <div className="template-gallery" aria-label="文档模板">
                {templates
                    .filter((t) =>
                        page === "notes"
                            ? [
                                  "reading",
                                  "idea",
                                  "meeting",
                                  "method",
                                  "comparison",
                              ].includes(t.id)
                            : t.type === "writing",
                    )
                    .map((t) => (
                        <button
                            key={t.id}
                            className="template-card"
                            onClick={() =>
                                setEditor({
                                    kind: page === "notes" ? "note" : "draft",
                                    content: t.content,
                                    fields: { note_type: t.type, folder },
                                })
                            }
                        >
                            <span className="template-symbol">
                                {t.label.slice(0, 1)}
                            </span>
                            <strong>{t.label}</strong>
                            <small>{t.description}</small>
                        </button>
                    ))}
            </div>
            <div className="records-filterbar">
                <select
                    aria-label="笔记类型"
                    value={type}
                    onChange={(e) => setType(e.target.value)}
                >
                    <option value="">全部类型</option>
                    {Object.entries(noteTypes).map(([key, label]) => (
                        <option key={key} value={key}>
                            {label}
                        </option>
                    ))}
                </select>
                <select
                    aria-label="笔记标签"
                    value={tag}
                    onChange={(e) => setTag(e.target.value)}
                >
                    <option value="">全部标签</option>
                    {[
                        ...new Set(
                            records.flatMap((r) =>
                                Array.isArray(r.version.fields.tags)
                                    ? r.version.fields.tags.map(String)
                                    : [],
                            ),
                        ),
                    ]
                        .sort()
                        .map((t) => (
                            <option key={t} value={t}>
                                {t}
                            </option>
                        ))}
                </select>
                <span className="toolbar-spacer" />
                <div className="segmented-control">
                    <button
                        className={view === "grid" ? "active" : ""}
                        aria-label="卡片视图"
                        onClick={() => setView("grid")}
                    >
                        <LayoutGrid size={15} />
                    </button>
                    <button
                        className={view === "list" ? "active" : ""}
                        aria-label="列表视图"
                        onClick={() => setView("list")}
                    >
                        <List size={15} />
                    </button>
                </div>
            </div>
            <div className="document-library">
                <aside className="document-folders">
                    <button
                        className={!folder ? "active" : ""}
                        onClick={() => setFolder("")}
                    >
                        <Folder size={14} />
                        全部文档<span>{records.length}</span>
                    </button>
                    {folders.map((name) => (
                        <button
                            className={folder === name ? "active" : ""}
                            key={name}
                            onClick={() => setFolder(name)}
                        >
                            <Folder size={14} />
                            {name}
                        </button>
                    ))}
                </aside>
                <section>
                    <label className="search-box document-search">
                        <Search size={15} />
                        <input
                            aria-label="搜索文档"
                            placeholder="搜索标题或正文"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                        />
                    </label>
                    <RecordCollection
                        items={items}
                        view={view}
                        selected={artifactIds}
                        onToggle={(id) =>
                            setArtifactIds((ids) =>
                                ids.includes(id)
                                    ? ids.filter((item) => item !== id)
                                    : ids.length < 20
                                      ? [...ids, id]
                                      : ids,
                            )
                        }
                        onOpen={openRecord}
                        kind={page === "notes" ? "note" : "draft"}
                        onNew={create}
                    />
                </section>
            </div>
        </>
    );
}
