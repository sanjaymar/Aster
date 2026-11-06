import {
    ArrowLeft,
    BookOpen,
    ChevronLeft,
    ChevronRight,
    Columns2,
    Download,
    FileText,
    Highlighter,
    List,
    MessageSquare,
    Minus,
    Plus,
    Search,
    Star,
    Trash2,
    Upload,
    X,
} from "lucide-react";
import {
    lazy,
    Suspense,
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react";
import {
    api,
    send,
    type Annotation,
    type Bundle,
    type ReadingState,
    type RecordItem,
    type Source,
    type SourceData,
} from "../../shared/api";
import { Spinner, Modal } from "../../shared/ui";
import { SourceDetails } from "./SourceDetails";
import Assistant from "../assistant/Assistant";
import type { OutlineItem } from "./PdfPage";
import { ReaderNotes } from "./ReaderNotes";
import { TextArticle } from "./TextArticle";
import { locateQuote } from "./selection";

const PdfDocument = lazy(() =>
    import("./PdfDocument").then((module) => ({ default: module.PdfDocument })),
);

type Selection = {
    start: number;
    end: number;
    quote: string;
    rectangles: number[][];
    page: number;
};
export function PaperReader({
    source: initialSource,
    projectId,
    bundle,
    onClose,
    onOpenNote,
    onError,
    onRefresh,
    onEvidence,
}: {
    source: Source;
    projectId: string;
    bundle: Bundle;
    onClose: () => void;
    onOpenNote: (note: RecordItem) => void;
    onError: (message: string) => void;
    onRefresh: () => void;
    onEvidence: (kind: string, id: string) => void;
}) {
    const source =
        bundle.sources.find((item) => item.id === initialSource.id) ||
        initialSource;
    const [editingSource, setEditingSource] = useState(false),
        [editingAnnotation, setEditingAnnotation] = useState<Annotation | null>(
            null,
        );
    const base = `/projects/${projectId}/sources/${source.id}`;
    const [data, setData] = useState<SourceData | null>(null),
        [version, setVersion] = useState(source.reading?.last_version_id || ""),
        [page, setPage] = useState(
            Math.max(0, (source.reading?.last_page || 1) - 1),
        ),
        [view, setView] = useState("text"),
        [ready, setReady] = useState(false);
    const [reading, setReading] = useState<ReadingState>(
        source.reading || {
            reading_status: "unread",
            starred: false,
            tags: [],
            last_page: 1,
        },
    );
    const [annotations, setAnnotations] = useState<Annotation[]>([]),
        [notes, setNotes] = useState<RecordItem[]>([]),
        [outline, setOutline] = useState<OutlineItem[]>([]),
        [search, setSearch] = useState(""),
        [leftTab, setLeftTab] = useState("outline"),
        [rightTab, setRightTab] = useState("notes"),
        [leftOpen, setLeftOpen] = useState(innerWidth >= 1000),
        [rightOpen, setRightOpen] = useState(innerWidth >= 900),
        [fontSize, setFontSize] = useState(18),
        [zoom, setZoom] = useState(1);
    const [selection, setSelection] = useState<Selection | null>(null),
        [comment, setComment] = useState(""),
        [seed, setSeed] = useState<{ text: string; key: number }>(),
        [question, setQuestion] = useState<{ text: string; key: number }>(),
        [saving, setSaving] = useState(false);
    const [leftWidth, setLeftWidth] = useState(210),
        [rightWidth, setRightWidth] = useState(360);
    const scroll = useRef<HTMLDivElement>(null),
        article = useRef<HTMLDivElement>(null),
        upload = useRef<HTMLInputElement>(null),
        positionTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
            undefined,
        ),
        savedScroll = useRef(source.reading?.last_scroll || 0),
        restorePending = useRef(true);
    const pinnedVersion = useRef<string>("");
    const pendingPage = useRef(page),
        activePage = useRef(page);
    activePage.current = page;
    const span = data?.pages[selection?.page ?? page];
    const pdf = data?.content_type === "application/pdf",
        pageUnit = pdf ? "页" : "段";
    const setOutlineStable = useCallback(
        (items: OutlineItem[]) => setOutline(items),
        [],
    );
    useEffect(() => {
        try {
            const prefs = JSON.parse(
                localStorage.getItem("aster:reader-layout") || "null",
            );
            if (prefs) {
                setLeftWidth(prefs.leftWidth || 210);
                setRightWidth(prefs.rightWidth || 360);
                setFontSize(prefs.fontSize || 18);
            }
        } catch {
            /* default layout */
        }
        const previous = document.body.style.overflow;
        document.body.style.overflow = "hidden";
        return () => {
            document.body.style.overflow = previous;
            clearTimeout(positionTimer.current);
        };
    }, []);
    useEffect(() => {
        localStorage.setItem(
            "aster:reader-layout",
            JSON.stringify({ leftWidth, rightWidth, fontSize }),
        );
    }, [leftWidth, rightWidth, fontSize]);
    useEffect(() => {
        let live = true;
        api<SourceData>(
            `${base}/pages${version ? `?version_id=${version}` : ""}`,
        )
            .then((result) => {
                if (!live) return;
                setData(result);
                pinnedVersion.current = result.version.id;
                setPage((current) => {
                    const index = Math.min(
                        current,
                        Math.max(0, result.pages.length - 1),
                    );
                    pendingPage.current = index;
                    activePage.current = index;
                    return index;
                });
                setView(
                    result.content_type === "application/pdf" ? "pdf" : "text",
                );
                setReady(true);
                void updateReading({
                    last_version_id: result.version.id,
                    ...(reading.reading_status === "unread"
                        ? { reading_status: "reading" as const }
                        : {}),
                });
            })
            .catch((error) => onError(error.message));
        return () => {
            live = false;
        };
    }, [base, version]);
    function refreshRelated() {
        void api<Annotation[]>(`${base}/annotations`)
            .then(setAnnotations)
            .catch((error) => onError(error.message));
        void api<RecordItem[]>(`${base}/notes`)
            .then(setNotes)
            .catch((error) => onError(error.message));
    }
    useEffect(refreshRelated, [base]);
    async function updateReading(values: Partial<ReadingState>) {
        try {
            const value = await api<ReadingState>(
                `${base}/reading`,
                send("PATCH", values),
            );
            setReading(value);
        } catch (error) {
            onError((error as Error).message);
        }
    }
    function pageTop(index: number) {
        const container = scroll.current;
        const element = container?.querySelector<HTMLElement>(
            `[data-reader-page="${index}"]`,
        );
        if (!container || !element) return null;
        return {
            element,
            top:
                element.getBoundingClientRect().top -
                container.getBoundingClientRect().top +
                container.scrollTop,
        };
    }
    function persistPosition() {
        const index = activePage.current,
            position = pageTop(index);
        const fraction =
            position && scroll.current
                ? (scroll.current.scrollTop - position.top) /
                  Math.max(1, position.element.offsetHeight)
                : 0;
        return updateReading({
            last_page: index + 1,
            last_scroll: Math.max(0, Math.min(1, fraction)),
            last_version_id: pinnedVersion.current || undefined,
        });
    }
    function restorePosition() {
        const position = pageTop(pendingPage.current);
        if (restorePending.current && scroll.current && position) {
            scroll.current.scrollTop =
                position.top +
                savedScroll.current * position.element.offsetHeight;
            restorePending.current = false;
        }
    }
    useEffect(() => {
        if (ready && view === "text") {
            const timer = setTimeout(restorePosition, 50);
            return () => clearTimeout(timer);
        }
    }, [ready, view, data?.version.id]);
    function navigate(next: number, anchor?: number) {
        if (!data) return;
        const index = Math.max(0, Math.min(next, data.pages.length - 1));
        clearTimeout(positionTimer.current);
        setSelection(null);
        savedScroll.current = 0;
        pendingPage.current = index;
        activePage.current = index;
        restorePending.current = true;
        setPage(index);
        requestAnimationFrame(() => {
            restorePosition();
            if (anchor !== undefined)
                document
                    .getElementById(`reading-${index}-${anchor}`)
                    ?.scrollIntoView({ block: "start" });
        });
        void updateReading({
            last_page: index + 1,
            last_scroll: 0,
            last_version_id: data.version.id,
        });
        if (innerWidth < 900) setLeftOpen(false);
    }
    function scrolled() {
        const container = scroll.current;
        if (!container || restorePending.current) return;
        const top = container.getBoundingClientRect().top + 100;
        let current = 0;
        for (const element of container.querySelectorAll<HTMLElement>(
            "[data-reader-page]",
        )) {
            if (element.getBoundingClientRect().top <= top)
                current = Number(element.dataset.readerPage);
            else break;
        }
        activePage.current = current;
        setPage(current);
        clearTimeout(positionTimer.current);
        positionTimer.current = setTimeout(() => void persistPosition(), 800);
    }
    function selected(rectangles: number[][] = [], index = page) {
        const span = data?.pages[index];
        const selected = window.getSelection();
        if (
            !span ||
            !selected?.toString().trim() ||
            !article.current?.contains(selected.anchorNode) ||
            !article.current?.contains(selected.focusNode)
        )
            return;
        if (span.extraction_error) {
            onError(
                "本页文字暂时无法提取；可以查看 PDF 原图，或切换到文字版本选取引用。",
            );
            return;
        }
        const result = locateQuote(span.text, selected.toString());
        if (result) {
            setSelection({ ...result, rectangles, page: index });
            setComment("");
        } else {
            setSelection(null);
            onError("选段无法唯一对应原文，请选择一段更完整的文字。");
        }
    }
    async function annotate() {
        if (!selection || !span) return;
        setSaving(true);
        try {
            await api(
                `${base}/annotations`,
                send("POST", {
                    source_span_id: span.id,
                    start_offset: selection.start,
                    end_offset: selection.end,
                    quote: selection.quote,
                    rectangles: selection.rectangles,
                    comment,
                }),
            );
            setSelection(null);
            setComment("");
            setRightTab("annotations");
            setRightOpen(true);
            refreshRelated();
        } catch (error) {
            onError((error as Error).message);
        } finally {
            setSaving(false);
        }
    }
    function createNote(text = selection?.quote) {
        if (!span) return;
        setSeed({
            text: `${text ? `> ${text.split("\n").join("\n> ")}\n\n` : ""}[[S:${span.id}]]\n\n`,
            key: Date.now(),
        });
        setRightTab("notes");
        setRightOpen(true);
        setSelection(null);
    }
    function ask() {
        if (!span) return;
        setQuestion({
            text: `请解释以下原文，并说明它与代谢组学研究的关系：\n\n${selection?.quote || span.text.slice(0, 1200)}\n\n[[S:${span.id}]]`,
            key: Date.now(),
        });
        setRightTab("chat");
        setRightOpen(true);
        setSelection(null);
    }
    async function addVersion(file: File) {
        const form = new FormData();
        form.append("file", file);
        form.append("source_id", source.id);
        form.append("title", source.title);
        setSaving(true);
        try {
            const result = await api<{ version_id: string }>(
                `/projects/${projectId}/sources`,
                { method: "POST", body: form },
            );
            savedScroll.current = 0;
            restorePending.current = true;
            pendingPage.current = 0;
            setPage(0);
            setVersion(result.version_id);
            onRefresh();
        } catch (error) {
            onError((error as Error).message);
        } finally {
            setSaving(false);
            if (upload.current) upload.current.value = "";
        }
    }
    function resize(
        side: "left" | "right",
        event: React.PointerEvent<HTMLDivElement>,
    ) {
        const start = event.clientX,
            width = side === "left" ? leftWidth : rightWidth,
            handle = event.currentTarget;
        handle.setPointerCapture(event.pointerId);
        handle.onpointermove = (movement) => {
            const next =
                width + (movement.clientX - start) * (side === "left" ? 1 : -1);
            if (side === "left")
                setLeftWidth(Math.max(160, Math.min(360, next)));
            else setRightWidth(Math.max(300, Math.min(600, next)));
        };
        handle.onpointerup = () => {
            handle.onpointermove = null;
            handle.onpointerup = null;
        };
    }
    const headings =
        data?.pages.flatMap((part, index) =>
            Array.from(part.text.matchAll(/^#{1,3}\s+(.+)$/gm)).map(
                (match) => ({
                    title: match[1],
                    index,
                    offset: Array.from(part.text.slice(0, match.index)).length,
                }),
            ),
        ) || [];
    const searchResults = search.trim()
        ? data?.pages
              .flatMap((part, index) => {
                  const position = part.text
                      .toLocaleLowerCase()
                      .indexOf(search.toLocaleLowerCase());
                  if (position < 0) return [];
                  return [
                      {
                          index,
                          text: part.text.slice(
                              Math.max(0, position - 40),
                              position + 120,
                          ),
                      },
                  ];
              })
              .slice(0, 50) || []
        : [];
    return (
        <section
            className={`reader-workspace ${leftOpen ? "reader-left-open" : ""} ${rightOpen ? "reader-right-open" : ""}`}
            role="dialog"
            aria-label="论文阅读器"
        >
            <header className="reading-header">
                <button
                    className="icon-button"
                    aria-label="返回文献库"
                    onClick={() => {
                        clearTimeout(positionTimer.current);
                        void persistPosition().finally(() => {
                            onRefresh();
                            onClose();
                        });
                    }}
                >
                    <ArrowLeft size={20} />
                </button>
                <button
                    className="icon-button"
                    aria-label="切换目录"
                    onClick={() => {
                        setLeftOpen((v) => !v);
                        if (innerWidth < 900) setRightOpen(false);
                    }}
                >
                    <List size={18} />
                </button>
                <strong title={source.title}>{source.title}</strong>
                <span className="reader-format">
                    {pdf
                        ? "PDF"
                        : source.content_level === "study_metadata"
                          ? "研究元数据"
                          : source.accession
                            ? "XML 文字全文"
                            : "文本"}
                </span>
                <div className="reading-header-actions">
                    <button
                        className={`icon-button ${reading.starred ? "selected" : ""}`}
                        aria-label="收藏文献"
                        onClick={() =>
                            void updateReading({ starred: !reading.starred })
                        }
                    >
                        <Star
                            size={17}
                            fill={reading.starred ? "currentColor" : "none"}
                        />
                    </button>
                    <button
                        className="icon-button"
                        aria-label="切换笔记栏"
                        onClick={() => {
                            setRightOpen((v) => !v);
                            if (innerWidth < 900) setLeftOpen(false);
                        }}
                    >
                        <Columns2 size={18} />
                    </button>
                </div>
            </header>
            <div
                className="reading-body"
                style={{
                    gridTemplateColumns: `${leftOpen ? leftWidth : 0}px minmax(0, 1fr) ${rightOpen ? rightWidth : 0}px`,
                }}
            >
                <aside className="reading-navigation" hidden={!leftOpen}>
                    <div className="segmented">
                        <button
                            className={leftTab === "outline" ? "active" : ""}
                            onClick={() => setLeftTab("outline")}
                        >
                            <List size={14} />
                            目录
                        </button>
                        <button
                            className={leftTab === "search" ? "active" : ""}
                            onClick={() => setLeftTab("search")}
                        >
                            <Search size={14} />
                            搜索
                        </button>
                    </div>
                    {leftTab === "search" ? (
                        <>
                            <input
                                aria-label="搜索文献正文"
                                placeholder="搜索正文"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                            />
                            {searchResults.map((result) => (
                                <button
                                    className="reader-outline-item"
                                    key={result.index}
                                    onClick={() => navigate(result.index)}
                                >
                                    <small>
                                        第 {result.index + 1} {pageUnit}
                                    </small>
                                    <span>{result.text}</span>
                                </button>
                            ))}
                        </>
                    ) : (
                        <div className="reader-outline">
                            {pdf && outline.length
                                ? outline.map((item, i) => (
                                      <button
                                          className="reader-outline-item"
                                          key={i}
                                          style={{
                                              paddingLeft: 12 + item.depth * 10,
                                          }}
                                          onClick={() =>
                                              navigate(item.page - 1)
                                          }
                                      >
                                          {item.title}
                                          <small>{item.page}</small>
                                      </button>
                                  ))
                                : headings.length
                                  ? headings.map((item, i) => (
                                        <button
                                            className="reader-outline-item"
                                            key={i}
                                            onClick={() =>
                                                navigate(
                                                    item.index,
                                                    item.offset,
                                                )
                                            }
                                        >
                                            {item.title}
                                        </button>
                                    ))
                                  : data?.pages.map((item, i) => (
                                        <button
                                            className={`reader-outline-item ${page === i ? "active" : ""}`}
                                            key={item.id}
                                            onClick={() => navigate(i)}
                                        >
                                            {item.text
                                                .split("\n")
                                                .find((line) => line.trim())
                                                ?.slice(0, 60) ||
                                                `${pageUnit} ${i + 1}`}
                                            <small>{i + 1}</small>
                                        </button>
                                    ))}
                        </div>
                    )}
                    <div
                        className="reader-resizer right"
                        onPointerDown={(event) => resize("left", event)}
                    />
                </aside>
                <main className="reading-main">
                    <div className="reading-tools">
                        {pdf && (
                            <div className="segmented">
                                <button
                                    className={view === "pdf" ? "active" : ""}
                                    onClick={() => setView("pdf")}
                                >
                                    PDF
                                </button>
                                <button
                                    className={view === "text" ? "active" : ""}
                                    onClick={() => setView("text")}
                                >
                                    文本
                                </button>
                            </div>
                        )}
                        <div className="inline">
                            <button
                                className="icon-button"
                                aria-label="缩小文字"
                                onClick={() =>
                                    view === "pdf"
                                        ? setZoom((z) => Math.max(0.5, z - 0.1))
                                        : setFontSize((size) =>
                                              Math.max(14, size - 1),
                                          )
                                }
                            >
                                <Minus size={14} />
                            </button>
                            <span>
                                {view === "pdf"
                                    ? `${Math.round(zoom * 100)}%`
                                    : `${fontSize}px`}
                            </span>
                            <button
                                className="icon-button"
                                aria-label="放大文字"
                                onClick={() =>
                                    view === "pdf"
                                        ? setZoom((z) => Math.min(2, z + 0.1))
                                        : setFontSize((size) =>
                                              Math.min(26, size + 1),
                                          )
                                }
                            >
                                <Plus size={14} />
                            </button>
                        </div>
                        <span className="toolbar-spacer" />
                        {data && (
                            <select
                                aria-label="文献版本"
                                value={data.version.id}
                                onChange={(e) => {
                                    savedScroll.current = 0;
                                    restorePending.current = true;
                                    setPage(0);
                                    pendingPage.current = 0;
                                    setVersion(e.target.value);
                                    setSelection(null);
                                }}
                            >
                                {data.versions.map((version) => (
                                    <option key={version.id} value={version.id}>
                                        v{version.number}
                                        {version.content_type ===
                                        "application/pdf"
                                            ? " · PDF"
                                            : " · 文本"}
                                    </option>
                                ))}
                            </select>
                        )}
                        <a
                            className="icon-button"
                            title="下载原文件"
                            href={`/api/assets/${data?.version.asset_id || source.asset_id}`}
                        >
                            <Download size={15} />
                        </a>
                        <button
                            className="icon-button"
                            aria-label="上传新版本"
                            disabled={saving}
                            onClick={() => upload.current?.click()}
                        >
                            <Upload size={15} />
                        </button>
                        <input
                            ref={upload}
                            type="file"
                            hidden
                            accept=".pdf,.txt,.md,.csv"
                            onChange={(e) => {
                                if (e.target.files?.[0])
                                    void addVersion(e.target.files[0]);
                            }}
                        />
                    </div>
                    <div
                        className="reading-scroll"
                        ref={scroll}
                        onScroll={scrolled}
                    >
                        <div ref={article} className="reader-article">
                            {!data ? (
                                <Spinner />
                            ) : pdf && view === "pdf" ? (
                                <Suspense fallback={<Spinner />}>
                                    <PdfDocument
                                        assetId={data.version.asset_id}
                                        pages={data.pages}
                                        zoom={zoom}
                                        annotations={annotations.filter(
                                            (item) =>
                                                item.source_version_id ===
                                                data.version.id,
                                        )}
                                        onOutline={setOutlineStable}
                                        onReady={restorePosition}
                                        onSelection={(index, rectangles) =>
                                            selected(rectangles, index)
                                        }
                                    />
                                </Suspense>
                            ) : (
                                <div className="reader-text-flow">
                                    {data.pages.map((part, index) => (
                                        <section
                                            key={part.id}
                                            data-reader-page={index}
                                            className="reading-text-section"
                                            onMouseUp={() =>
                                                selected([], index)
                                            }
                                        >
                                            <TextArticle
                                                text={
                                                    part.text ||
                                                    "本页无可提取文字"
                                                }
                                                annotations={annotations.filter(
                                                    (item) =>
                                                        item.source_span_id ===
                                                        part.id,
                                                )}
                                                fontSize={fontSize}
                                                page={index}
                                            />
                                        </section>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                    {selection && (
                        <div
                            className="selection-toolbar"
                            role="region"
                            aria-label="选段操作"
                        >
                            <span>{selection.quote.length} 字</span>
                            <input
                                aria-label="标注评论"
                                placeholder="添加评论"
                                value={comment}
                                onChange={(e) => setComment(e.target.value)}
                            />
                            <button
                                className="text-button"
                                disabled={saving}
                                onClick={() => void annotate()}
                            >
                                <Highlighter size={14} />
                                标注
                            </button>
                            <button
                                className="text-button"
                                onClick={() => createNote()}
                            >
                                <FileText size={14} />
                                记笔记
                            </button>
                            <button className="text-button" onClick={ask}>
                                <MessageSquare size={14} />
                                询问选段
                            </button>
                            <button
                                className="icon-button"
                                aria-label="取消选段"
                                onClick={() => setSelection(null)}
                            >
                                <X size={13} />
                            </button>
                        </div>
                    )}
                    <footer className="reading-pagination">
                        <button
                            className="icon-button"
                            aria-label="上一页"
                            disabled={!page}
                            onClick={() => navigate(page - 1)}
                        >
                            <ChevronLeft size={17} />
                        </button>
                        <select
                            aria-label="页码"
                            value={page}
                            onChange={(e) => navigate(Number(e.target.value))}
                        >
                            {data?.pages.map((part, index) => (
                                <option key={part.id} value={index}>
                                    {index + 1} / {data.pages.length}
                                </option>
                            ))}
                        </select>
                        <button
                            className="icon-button"
                            aria-label="下一页"
                            disabled={!data || page >= data.pages.length - 1}
                            onClick={() => navigate(page + 1)}
                        >
                            <ChevronRight size={17} />
                        </button>
                        <span>{pageUnit}</span>
                    </footer>
                </main>
                <aside className="reading-sidebar" hidden={!rightOpen}>
                    <div
                        className="reader-resizer left"
                        onPointerDown={(event) => resize("right", event)}
                    />
                    <div className="reading-sidebar-tabs">
                        {[
                            ["notes", "笔记"],
                            ["annotations", "标注"],
                            ["chat", "问答"],
                            ["info", "信息"],
                        ].map(([key, label]) => (
                            <button
                                key={key}
                                className={rightTab === key ? "active" : ""}
                                onClick={() => setRightTab(key)}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                    <div
                        className="reader-sidebar-content"
                        hidden={rightTab !== "notes"}
                    >
                        <div className="reader-quick-actions">
                            <button
                                className="text-button"
                                onClick={() => createNote("")}
                            >
                                <Plus size={14} />
                                引用本{pageUnit}写笔记
                            </button>
                        </div>
                        <ReaderNotes
                            projectId={projectId}
                            source={source}
                            notes={notes}
                            seed={seed}
                            onOpen={(note) => {
                                void persistPosition();
                                onOpenNote(note);
                            }}
                            onSaved={() => {
                                refreshRelated();
                                onRefresh();
                            }}
                            onError={onError}
                        />
                    </div>
                    <div
                        className="reader-sidebar-content"
                        hidden={rightTab !== "annotations"}
                    >
                        {annotations.length ? (
                            annotations.map((annotation) => (
                                <article
                                    className="annotation-card"
                                    key={annotation.id}
                                >
                                    <button
                                        onClick={() => {
                                            if (
                                                annotation.source_version_id !==
                                                data?.version.id
                                            ) {
                                                clearTimeout(
                                                    positionTimer.current,
                                                );
                                                setSelection(null);
                                                savedScroll.current = 0;
                                                restorePending.current = true;
                                                pendingPage.current =
                                                    annotation.page - 1;
                                                setPage(annotation.page - 1);
                                                setVersion(
                                                    annotation.source_version_id,
                                                );
                                            } else
                                                navigate(annotation.page - 1);
                                        }}
                                    >
                                        <small>
                                            v{annotation.version} · 第{" "}
                                            {annotation.page} {pageUnit}
                                        </small>
                                        <blockquote>
                                            {annotation.quote}
                                        </blockquote>
                                        {annotation.comment && (
                                            <p>{annotation.comment}</p>
                                        )}
                                    </button>
                                    <div className="inline spread">
                                        <button
                                            className="text-button"
                                            onClick={() => {
                                                setSeed({
                                                    text: `> ${annotation.quote.split("\n").join("\n> ")}\n\n${annotation.comment}\n\n[[S:${annotation.source_span_id}]]\n`,
                                                    key: Date.now(),
                                                });
                                                setRightTab("notes");
                                            }}
                                        >
                                            加入笔记
                                        </button>
                                        <button
                                            className="icon-button"
                                            aria-label="删除标注"
                                            onClick={() =>
                                                api(
                                                    `${base}/annotations/${annotation.id}`,
                                                    { method: "DELETE" },
                                                )
                                                    .then(refreshRelated)
                                                    .catch((error) =>
                                                        onError(error.message),
                                                    )
                                            }
                                        >
                                            <Trash2 size={13} />
                                        </button>
                                        <button
                                            className="text-button"
                                            onClick={() =>
                                                setEditingAnnotation(annotation)
                                            }
                                        >
                                            编辑评论
                                        </button>
                                    </div>
                                </article>
                            ))
                        ) : (
                            <p className="plain-empty">暂无标注</p>
                        )}
                    </div>
                    <div className="reader-chat" hidden={rightTab !== "chat"}>
                        <Assistant
                            pinnedDocument
                            initialScope="selected"
                            draftQuestion={question}
                            sourceVersionIds={data ? [data.version.id] : []}
                            projectId={projectId}
                            bundle={{
                                ...bundle,
                                sources: [source],
                                records: notes,
                            }}
                            sourceIds={[source.id]}
                            setSourceIds={() => {}}
                            artifactIds={[]}
                            setArtifactIds={() => {}}
                            defaultMode="chat"
                            onError={onError}
                            onRefresh={onRefresh}
                            onEvidence={onEvidence}
                            onClose={() => setRightOpen(false)}
                        />
                    </div>
                    <div
                        className="reader-sidebar-content reader-info"
                        hidden={rightTab !== "info"}
                    >
                        <h3>{source.title}</h3>
                        <button
                            className="text-button"
                            onClick={() => setEditingSource(true)}
                        >
                            编辑资料
                        </button>
                        {source.content_level === "study_metadata" && (
                            <p className="notice">
                                研究元数据；原始谱图未下载。
                            </p>
                        )}
                        {source.original_pdf?.is_retracted && (
                            <p className="notice">PMC 已将此论文标记为撤稿。</p>
                        )}
                        <p>{source.authors}</p>
                        <p>
                            {source.year} {source.doi}
                        </p>
                        {source.accession && (
                            <p className="muted small">
                                {source.repository} · {source.accession}
                            </p>
                        )}
                        {source.original_pdf && (
                            <p>
                                <a
                                    href={source.original_pdf.url}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    NCBI PMC 官方 PDF
                                </a>
                            </p>
                        )}
                        {!!data?.pages.some(
                            (part) => part.extraction_error,
                        ) && (
                            <p className="notice">
                                部分页面无法提取文字，原始图像仍可阅读；需要引用这些页的文字时，可切换到文本版本。
                            </p>
                        )}
                        <label>
                            阅读状态
                            <select
                                aria-label="阅读状态"
                                value={reading.reading_status}
                                onChange={(e) =>
                                    void updateReading({
                                        reading_status: e.target
                                            .value as ReadingState["reading_status"],
                                    })
                                }
                            >
                                <option value="unread">未读</option>
                                <option value="reading">在读</option>
                                <option value="read">已读</option>
                            </select>
                        </label>
                        <label>
                            标签
                            <input
                                aria-label="文献标签"
                                defaultValue={reading.tags.join(", ")}
                                placeholder="逗号分隔"
                                onBlur={(e) =>
                                    void updateReading({
                                        tags: e.target.value
                                            .split(/[,，]/)
                                            .map((tag) => tag.trim())
                                            .filter(Boolean),
                                    })
                                }
                            />
                        </label>
                        {source.url && (
                            <a
                                href={source.url}
                                target="_blank"
                                rel="noreferrer"
                            >
                                打开来源
                            </a>
                        )}
                        <button
                            className="text-button"
                            onClick={() =>
                                void updateReading({ reading_status: "read" })
                            }
                        >
                            <BookOpen size={14} />
                            标为已读
                        </button>
                    </div>
                </aside>
            </div>
            {editingSource && (
                <SourceDetails
                    source={source}
                    projectId={projectId}
                    onClose={() => setEditingSource(false)}
                    onSaved={onRefresh}
                    onError={onError}
                />
            )}
            {editingAnnotation && (
                <Modal
                    title="编辑标注评论"
                    onClose={() => setEditingAnnotation(null)}
                >
                    <blockquote>{editingAnnotation.quote}</blockquote>
                    <textarea
                        aria-label="标注评论正文"
                        value={editingAnnotation.comment}
                        maxLength={10000}
                        onChange={(e) =>
                            setEditingAnnotation({
                                ...editingAnnotation,
                                comment: e.target.value,
                            })
                        }
                    />
                    <footer className="form-footer">
                        <span />
                        <button
                            className="button primary"
                            onClick={async () => {
                                try {
                                    await api(
                                        `${base}/annotations/${editingAnnotation.id}`,
                                        send("PATCH", {
                                            comment: editingAnnotation.comment,
                                        }),
                                    );
                                    setEditingAnnotation(null);
                                    refreshRelated();
                                } catch (error) {
                                    onError((error as Error).message);
                                }
                            }}
                        >
                            保存评论
                        </button>
                    </footer>
                </Modal>
            )}
        </section>
    );
}
