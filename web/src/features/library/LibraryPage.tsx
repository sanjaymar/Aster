import {
    ArrowUpRight,
    BookOpen,
    Search,
    Star,
    Upload,
    Pencil,
} from "lucide-react";
import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { api, send, type Bundle, type Source } from "../../shared/api";
import { Empty } from "../../shared/ui";
import { SourceDetails } from "./SourceDetails";
const readingLabels = { unread: "未读", reading: "在读", read: "已读" };
export function LibraryPage({
    projectId,
    bundle,
    sourceIds,
    setSourceIds,
    setImportModal,
    setReader,
    onRefresh,
    onError,
}: {
    projectId: string;
    bundle: Bundle;
    sourceIds: string[];
    setSourceIds: Dispatch<SetStateAction<string[]>>;
    setImportModal: (open: boolean) => void;
    setReader: (source: Source) => void;
    onRefresh: () => void;
    onError: (message: string) => void;
}) {
    const [editing, setEditing] = useState<Source | null>(null);
    const [query, setQuery] = useState(""),
        [status, setStatus] = useState("all"),
        [tag, setTag] = useState(""),
        [page, setPage] = useState(0),
        [sort, setSort] = useState("recent");
    const tags = [
        ...new Set(
            bundle.sources.flatMap((source) => source.reading?.tags || []),
        ),
    ].sort();
    const filtered = useMemo(
        () =>
            bundle.sources
                .filter((source) => {
                    const text = [
                        source.title,
                        source.authors,
                        source.doi,
                        source.accession,
                        ...(source.reading?.tags || []),
                    ]
                        .join(" ")
                        .toLocaleLowerCase();
                    return (
                        text.includes(query.toLocaleLowerCase()) &&
                        (status === "all" ||
                            (status === "starred"
                                ? source.reading?.starred
                                : (source.reading?.reading_status ||
                                      "unread") === status)) &&
                        (!tag || source.reading?.tags.includes(tag))
                    );
                })
                .sort((a, b) =>
                    sort === "title"
                        ? a.title.localeCompare(b.title)
                        : sort === "year"
                          ? Number(b.year || 0) - Number(a.year || 0)
                          : 0,
                ),
        [bundle.sources, query, status, tag, sort],
    );
    const size = 25,
        current = Math.min(
            page,
            Math.max(0, Math.ceil(filtered.length / size) - 1),
        );
    async function star(source: Source) {
        try {
            await api(
                `/projects/${projectId}/sources/${source.id}/reading`,
                send("PATCH", { starred: !source.reading?.starred }),
            );
            onRefresh();
        } catch (error) {
            onError((error as Error).message);
        }
    }
    return (
        <section className="library-page" aria-label="文献库">
            <div className="page-heading">
                <h1>
                    文献阅读{" "}
                    <small className="heading-count">
                        {bundle.sources.length}
                    </small>
                </h1>
                <button
                    className="button primary"
                    onClick={() => setImportModal(true)}
                >
                    <Upload size={15} />
                    导入文献
                </button>
            </div>
            <div className="library-toolbar">
                <label className="search-box library-search">
                    <Search size={16} />
                    <input
                        aria-label="搜索文献"
                        placeholder="标题、作者、DOI、标签"
                        value={query}
                        onChange={(e) => {
                            setQuery(e.target.value);
                            setPage(0);
                        }}
                    />
                </label>
                <select
                    aria-label="按阅读状态筛选"
                    value={status}
                    onChange={(e) => {
                        setStatus(e.target.value);
                        setPage(0);
                    }}
                >
                    <option value="all">全部文献</option>
                    <option value="starred">收藏</option>
                    <option value="unread">未读</option>
                    <option value="reading">在读</option>
                    <option value="read">已读</option>
                </select>
                <select
                    aria-label="按标签筛选"
                    value={tag}
                    onChange={(e) => {
                        setTag(e.target.value);
                        setPage(0);
                    }}
                >
                    <option value="">全部标签</option>
                    {tags.map((tag) => (
                        <option key={tag}>{tag}</option>
                    ))}
                </select>
                <select
                    aria-label="文献排序"
                    value={sort}
                    onChange={(e) => setSort(e.target.value)}
                >
                    <option value="recent">最近导入</option>
                    <option value="year">发表年份</option>
                    <option value="title">标题</option>
                </select>
            </div>
            {bundle.sources.length ? (
                <>
                    <div className="library-list">
                        <table className="library-table">
                            <caption className="sr-only">文献列表</caption>
                            <colgroup>
                                <col className="library-col-select" />
                                <col className="library-col-star" />
                                <col />
                                <col className="library-col-year" />
                                <col className="library-col-state" />
                                <col className="library-col-actions" />
                            </colgroup>
                            <thead>
                                <tr>
                                    <th scope="col">
                                        <span className="sr-only">选择</span>
                                    </th>
                                    <th scope="col">
                                        <span className="sr-only">收藏</span>
                                    </th>
                                    <th scope="col">标题</th>
                                    <th scope="col" className="library-year">
                                        年份
                                    </th>
                                    <th scope="col">状态</th>
                                    <th scope="col">
                                        <span className="sr-only">操作</span>
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {filtered
                                    .slice(current * size, (current + 1) * size)
                                    .map((source) => (
                                        <tr
                                            key={source.id}
                                            data-source-id={source.id}
                                        >
                                            <td className="library-select-cell">
                                                <input
                                                    type="checkbox"
                                                    aria-label={`选择资料 ${source.title}`}
                                                    checked={sourceIds.includes(
                                                        source.id,
                                                    )}
                                                    disabled={
                                                        !sourceIds.includes(
                                                            source.id,
                                                        ) &&
                                                        sourceIds.length >= 10
                                                    }
                                                    onChange={() =>
                                                        setSourceIds((ids) =>
                                                            ids.includes(
                                                                source.id,
                                                            )
                                                                ? ids.filter(
                                                                      (id) =>
                                                                          id !==
                                                                          source.id,
                                                                  )
                                                                : [
                                                                      ...ids,
                                                                      source.id,
                                                                  ],
                                                        )
                                                    }
                                                />
                                            </td>
                                            <td className="library-star-cell">
                                                <button
                                                    className={`icon-button library-star ${source.reading?.starred ? "selected" : ""}`}
                                                    aria-label={`收藏 ${source.title}`}
                                                    onClick={() =>
                                                        void star(source)
                                                    }
                                                >
                                                    <Star
                                                        size={14}
                                                        fill={
                                                            source.reading
                                                                ?.starred
                                                                ? "currentColor"
                                                                : "none"
                                                        }
                                                    />
                                                </button>
                                            </td>
                                            <td className="library-details">
                                                <button
                                                    className="library-title"
                                                    title={source.title}
                                                    onClick={() =>
                                                        setReader(source)
                                                    }
                                                >
                                                    <span className="source-format">
                                                        {source.content_level ===
                                                        "study_metadata"
                                                            ? "研究元数据"
                                                            : source.content_type ===
                                                                "application/pdf"
                                                              ? "PDF"
                                                              : source.accession
                                                                ? "XML 文本"
                                                                : "文本"}
                                                    </span>
                                                    {source.title}
                                                </button>
                                                <p
                                                    className="library-authors"
                                                    title={source.authors}
                                                >
                                                    {source.authors || "—"}
                                                </p>
                                                <small className="library-reference">
                                                    {source.year && (
                                                        <span className="library-year-inline">
                                                            {source.year} ·{" "}
                                                        </span>
                                                    )}
                                                    {source.accession ||
                                                        source.doi ||
                                                        ""}
                                                </small>
                                                <div className="library-tags">
                                                    {source.reading?.tags.map(
                                                        (tag) => (
                                                            <span key={tag}>
                                                                {tag}
                                                            </span>
                                                        ),
                                                    )}
                                                </div>
                                            </td>
                                            <td className="library-year">
                                                {source.year || "—"}
                                            </td>
                                            <td className="library-state">
                                                <span
                                                    className={`reading-badge ${source.reading?.reading_status || "unread"}`}
                                                >
                                                    {
                                                        readingLabels[
                                                            source.reading
                                                                ?.reading_status ||
                                                                "unread"
                                                        ]
                                                    }
                                                </span>
                                            </td>
                                            <td className="library-action-cell">
                                                <div className="library-actions">
                                                    <button
                                                        className="text-button"
                                                        onClick={() =>
                                                            setReader(source)
                                                        }
                                                    >
                                                        <BookOpen size={14} />
                                                        阅读
                                                    </button>
                                                    <button
                                                        className="icon-button"
                                                        aria-label={`编辑资料 ${source.title}`}
                                                        onClick={() =>
                                                            setEditing(source)
                                                        }
                                                    >
                                                        <Pencil size={14} />
                                                    </button>
                                                    {source.url && (
                                                        <a
                                                            className="icon-button"
                                                            title="来源"
                                                            href={source.url}
                                                            target="_blank"
                                                            rel="noreferrer"
                                                        >
                                                            <ArrowUpRight
                                                                size={13}
                                                            />
                                                        </a>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                            </tbody>
                        </table>
                        {!filtered.length && (
                            <p className="plain-empty">无匹配文献</p>
                        )}
                    </div>
                    <div className="library-pagination">
                        <span>
                            {filtered.length} 篇
                            {sourceIds.length
                                ? ` · 已选 ${sourceIds.length} 篇用于问答`
                                : ""}
                        </span>
                        <button
                            className="button secondary"
                            disabled={!current}
                            onClick={() => setPage(current - 1)}
                        >
                            上一页
                        </button>
                        <span>
                            {current + 1} /{" "}
                            {Math.max(1, Math.ceil(filtered.length / size))}
                        </span>
                        <button
                            className="button secondary"
                            disabled={(current + 1) * size >= filtered.length}
                            onClick={() => setPage(current + 1)}
                        >
                            下一页
                        </button>
                    </div>
                </>
            ) : (
                <Empty
                    title="暂无文献"
                    action={
                        <button
                            className="button secondary"
                            onClick={() => setImportModal(true)}
                        >
                            导入文件
                        </button>
                    }
                />
            )}
            {editing && (
                <SourceDetails
                    projectId={projectId}
                    source={editing}
                    onClose={() => setEditing(null)}
                    onSaved={onRefresh}
                    onError={onError}
                />
            )}
        </section>
    );
}
