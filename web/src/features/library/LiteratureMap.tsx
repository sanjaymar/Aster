import { useEffect, useMemo, useState } from "react";
import {
    BookOpen,
    FileText,
    Network,
    LayoutList,
    Search,
    Presentation,
    WandSparkles,
    ArrowUpRight,
    X,
} from "lucide-react";
import { api, type Source, type RecordItem } from "../../shared/api";
import { Spinner } from "../../shared/ui";
import { TopicGraph, type MapData } from "./TopicGraph";

export function LiteratureMap({
    projectId,
    sources,
    records,
    onOpen,
    onRecord,
    onNote,
    onSlides,
    onError,
}: {
    projectId: string;
    sources: Source[];
    records: RecordItem[];
    onOpen: (s: Source) => void;
    onRecord: (r: RecordItem) => void;
    onNote: (s: Source) => void;
    onSlides: (s: Source) => void;
    onError: (s: string) => void;
}) {
    const [data, setData] = useState<MapData>();
    const [query, setQuery] = useState(""),
        [topic, setTopic] = useState(""),
        [focus, setFocus] = useState("");
    const [view, setView] = useState<"map" | "list">("map"),
        [status, setStatus] = useState("");
    const [loading, setLoading] = useState(true);
    const signature = JSON.stringify([
        sources.map((s) => [s.id, s.version_id, s.title, s.year, s.reading]),
        records.map((r) => [r.id, r.revision]),
    ]);
    useEffect(() => {
        let live = true;
        setLoading(true);
        api<MapData>(`/projects/${projectId}/map`)
            .then((value) => {
                if (live) setData(value);
            })
            .catch((e) => onError(e.message))
            .finally(() => {
                if (live) setLoading(false);
            });
        return () => {
            live = false;
        };
    }, [projectId, signature]);
    const matches = useMemo(
        () =>
            data?.nodes.filter(
                (n) =>
                    (!topic || n.topic === topic) &&
                    (!status || n.reading_status === status) &&
                    `${n.title} ${n.authors} ${n.year} ${n.keywords.join(" ")} ${n.tags.join(" ")}`
                        .toLowerCase()
                        .includes(query.toLowerCase()),
            ) || [],
        [data, query, topic, status],
    );
    const selected = data?.nodes.find((n) => n.id === focus);
    const related =
        data?.edges
            .filter((e) => e.source === focus || e.target === focus)
            .sort((a, b) => b.score - a.score)
            .map((e) => ({
                paper: data.nodes.find(
                    (n) => n.id === (e.source === focus ? e.target : e.source),
                )!,
                score: e.score,
            }))
            .slice(0, 6) || [];
    const open = (id: string) => {
        const s = sources.find((s) => s.id === id);
        if (s) onOpen(s);
    };
    return (
        <div className="atlas-page">
            <header className="page-heading">
                <div>
                    <span className="atlas-eyebrow">LIBRARY ATLAS</span>
                    <h1>
                        文献地图{" "}
                        <small className="heading-count">
                            {sources.length}
                        </small>
                    </h1>
                </div>
                <div className="atlas-switch">
                    <button
                        className={view === "map" ? "active" : ""}
                        onClick={() => setView("map")}
                    >
                        <Network size={15} />
                        主题图谱
                    </button>
                    <button
                        className={view === "list" ? "active" : ""}
                        onClick={() => setView("list")}
                    >
                        <LayoutList size={15} />
                        文献列表
                    </button>
                </div>
            </header>
            <div className="atlas-toolbar">
                <label className="atlas-search">
                    <Search size={16} />
                    <input
                        aria-label="搜索文献地图"
                        placeholder="搜索论文、作者、关键词"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                </label>
                <select
                    aria-label="地图阅读状态"
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                >
                    <option value="">全部阅读状态</option>
                    <option value="unread">未读</option>
                    <option value="reading">在读</option>
                    <option value="read">已读</option>
                </select>
                <span>{data?.stats.topics || 0} 个主题</span>
                <span>{data?.stats.notes || 0} 篇笔记</span>
                <span>{data?.stats.read || 0} 篇已读</span>
            </div>
            <div className="atlas-workspace">
                <aside className="atlas-topics">
                    <div className="atlas-panel-title">主题分组</div>
                    <button
                        className={!topic ? "active" : ""}
                        onClick={() => setTopic("")}
                    >
                        <span>全部文献</span>
                        <small>{sources.length}</small>
                    </button>
                    {data?.topics.map((t) => (
                        <button
                            key={t.id}
                            className={topic === t.id ? "active" : ""}
                            onClick={() => {
                                setTopic(t.id);
                                setFocus("");
                            }}
                        >
                            <i style={{ background: t.color }} />
                            <span>
                                {t.label}
                                <em>{t.keywords.slice(2).join(" / ")}</em>
                            </span>
                            <small>{t.count}</small>
                        </button>
                    ))}
                    <p>按论文内容自动分组。导入与修改文献后更新。</p>
                </aside>
                <section className="atlas-stage">
                    <div className="atlas-stage-heading">
                        <strong>
                            {data?.topics.find((t) => t.id === topic)?.label ||
                                "全部主题"}
                        </strong>
                        <span>{matches.length} 篇</span>
                    </div>
                    {loading ? (
                        <div className="atlas-loading">
                            <Spinner />
                        </div>
                    ) : data && view === "map" ? (
                        <TopicGraph
                            data={data}
                            visible={matches.map((n) => n.id)}
                            focus={focus}
                            onSelect={setFocus}
                        />
                    ) : (
                        <div className="atlas-cards">
                            {matches.map((n) => (
                                <button
                                    className={focus === n.id ? "active" : ""}
                                    key={n.id}
                                    onClick={() => setFocus(n.id)}
                                >
                                    <span
                                        className="atlas-dot"
                                        style={{ background: n.color }}
                                    />
                                    <small>{n.journal || n.year}</small>
                                    <h3>{n.title}</h3>
                                    <p>{n.keywords.join(" · ")}</p>
                                    <footer>
                                        {n.year}
                                        <span>{n.notes.length} 篇笔记</span>
                                    </footer>
                                </button>
                            ))}
                        </div>
                    )}
                    {!loading && !matches.length && (
                        <div className="atlas-empty">没有匹配的论文</div>
                    )}
                    <div className="atlas-legend">
                        <span>
                            <i />
                            论文
                        </span>
                        <span>连线：内容相似</span>
                        <span>点击节点查看原文与笔记</span>
                    </div>
                </section>
                <aside className="atlas-detail">
                    {selected ? (
                        <>
                            <div className="atlas-panel-title">
                                论文详情
                                <button
                                    aria-label="关闭论文详情"
                                    onClick={() => setFocus("")}
                                >
                                    <X size={14} />
                                </button>
                            </div>
                            <div className="atlas-paper-meta">
                                <span style={{ color: selected.color }}>
                                    {
                                        data?.topics.find(
                                            (t) => t.id === selected.topic,
                                        )?.label
                                    }
                                </span>
                                <span>{selected.year}</span>
                            </div>
                            <h2>{selected.title}</h2>
                            <p className="atlas-authors">{selected.authors}</p>
                            <p className="atlas-journal">{selected.journal}</p>
                            <div className="atlas-paper-actions">
                                <button
                                    className="button primary"
                                    onClick={() => open(selected.id)}
                                >
                                    <BookOpen size={14} />
                                    阅读论文
                                </button>
                                <button
                                    className="button secondary"
                                    onClick={() => {
                                        const s = sources.find(
                                            (s) => s.id === focus,
                                        );
                                        if (s) onNote(s);
                                    }}
                                >
                                    <WandSparkles size={14} />
                                    生成笔记
                                </button>
                                <button
                                    className="button secondary"
                                    onClick={() => {
                                        const s = sources.find(
                                            (s) => s.id === focus,
                                        );
                                        if (s) onSlides(s);
                                    }}
                                >
                                    <Presentation size={14} />
                                    制作汇报
                                </button>
                            </div>
                            <div className="atlas-keywords">
                                {selected.keywords.map((k) => (
                                    <button key={k} onClick={() => setQuery(k)}>
                                        {k}
                                    </button>
                                ))}
                            </div>
                            <details open className="atlas-abstract">
                                <summary>摘要 / 原文摘录</summary>
                                <p>{selected.abstract || "暂无可提取文本"}</p>
                            </details>
                            <section className="atlas-related">
                                <h3>
                                    <FileText size={14} />
                                    阅读笔记{" "}
                                    <small>{selected.notes.length}</small>
                                </h3>
                                {selected.notes.map((n) => (
                                    <button
                                        key={n.id}
                                        onClick={() => {
                                            const r = records.find(
                                                (r) => r.id === n.id,
                                            );
                                            if (r) onRecord(r);
                                        }}
                                    >
                                        {n.title}
                                        <ArrowUpRight size={13} />
                                    </button>
                                ))}
                                {!selected.notes.length && <p>尚未记录笔记</p>}
                            </section>
                            <section className="atlas-related">
                                <h3>相关论文</h3>
                                {related.map(({ paper, score }) => (
                                    <button
                                        key={paper.id}
                                        onClick={() => setFocus(paper.id)}
                                    >
                                        <span>
                                            {paper.title}
                                            <small>
                                                文本相似度 {score.toFixed(2)}
                                            </small>
                                        </span>
                                        <ArrowUpRight size={13} />
                                    </button>
                                ))}
                            </section>
                        </>
                    ) : (
                        <>
                            <div className="atlas-panel-title">探索文献库</div>
                            <div className="atlas-intro">
                                <Network size={26} />
                                <h2>从一个主题开始</h2>
                                <p>
                                    选择左侧主题或点击论文节点，查看摘要、相关论文与阅读笔记。
                                </p>
                            </div>
                            <div className="atlas-recent">
                                {matches.slice(0, 5).map((n) => (
                                    <button
                                        key={n.id}
                                        onClick={() => setFocus(n.id)}
                                    >
                                        <span style={{ background: n.color }} />
                                        {n.title}
                                        <ArrowUpRight size={14} />
                                    </button>
                                ))}
                            </div>
                        </>
                    )}
                </aside>
            </div>
        </div>
    );
}
