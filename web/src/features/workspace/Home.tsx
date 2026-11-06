import { ArrowUp, ArrowUpRight, Download, Plus } from "lucide-react";
import { useState } from "react";
import type { Bundle, Project, RecordItem, Source } from "../../shared/api";
import { date, kindLabels, Spinner } from "../../shared/components";

export type ResearchTask = {
    prompt: string;
    mode: string;
    scope: string;
    responseStyle: string;
    sourceIds?: string[];
    artifactIds?: string[];
    skillId?: string;
    modelId?: string;
};
type Props = {
    project: Project;
    bundle: Bundle;
    selectedCount: number;
    onStart: (task: ResearchTask) => Promise<void>;
    onError: (message: string) => void;
    onImport: () => void;
    onNote: () => void;
    onMap: () => void;
    onSlides: () => void;
    onEdit: () => void;
    onRecord: (record: RecordItem) => void;
    onSource: (source: Source) => void;
};

export function ResearchHome({
    project,
    bundle,
    selectedCount,
    onStart,
    onError,
    onImport,
    onNote,
    onMap,
    onSlides,
    onEdit,
    onRecord,
    onSource,
}: Props) {
    const [prompt, setPrompt] = useState("");
    const [scope, setScope] = useState("project");
    const [responseStyle, setResponseStyle] = useState("auto");
    const [busy, setBusy] = useState(false);
    async function submit() {
        if (!prompt.trim() || busy) return;
        setBusy(true);
        try {
            await onStart({
                prompt: prompt.trim(),
                scope,
                mode: "chat",
                responseStyle,
            });
            setPrompt("");
        } catch (error) {
            onError((error as Error).message);
        } finally {
            setBusy(false);
        }
    }
    const actions = [
        { label: "文献", count: bundle.sources.length, click: onImport },
        {
            label: "笔记",
            count: bundle.records.filter((r) => r.kind === "note").length,
            click: onNote,
        },
        { label: "文献地图", count: bundle.sources.length, click: onMap },
        {
            label: "汇报",
            count: bundle.records.filter((r) => r.kind === "deck").length,
            click: onSlides,
        },
    ];
    return (
        <div className="project-dashboard">
            <div className="dashboard-heading">
                <div>
                    <span className="eyebrow">PROJECT</span>
                    <h1>{project.title}</h1>
                </div>
                <div className="inline">
                    <button className="button secondary" onClick={onEdit}>
                        编辑项目
                    </button>
                    <a
                        className="button secondary"
                        href={`/api/projects/${project.id}/export`}
                    >
                        <Download size={14} />
                        导出
                    </a>
                </div>
            </div>
            {project.description && (
                <div className="project-description">{project.description}</div>
            )}
            <div className="dashboard-stats">
                {actions.map((action) => (
                    <button key={action.label} onClick={action.click}>
                        <span>{action.label}</span>
                        <strong>{action.count}</strong>
                        <Plus size={15} />
                    </button>
                ))}
            </div>
            <section className="dashboard-task">
                <div className="section-heading">
                    <h2>问答</h2>
                </div>
                <form
                    className="home-composer"
                    onSubmit={(event) => {
                        event.preventDefault();
                        void submit();
                    }}
                >
                    <label className="sr-only" htmlFor="research-prompt">
                        研究问题
                    </label>
                    <textarea
                        id="research-prompt"
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        maxLength={20000}
                        placeholder="向项目资料提问…"
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                                e.preventDefault();
                                void submit();
                            }
                        }}
                    />
                    <div className="home-compose-footer">
                        <div className="home-options">
                            <select
                                aria-label="首页检索范围"
                                value={scope}
                                onChange={(e) => setScope(e.target.value)}
                            >
                                <option value="project">本项目资料</option>
                                <option value="selected">
                                    已选 {selectedCount} 份材料
                                </option>
                            </select>
                            <select
                                aria-label="首页回答方式"
                                value={responseStyle}
                                onChange={(e) =>
                                    setResponseStyle(e.target.value)
                                }
                            >
                                <option value="grounded">资料问答</option>
                                <option value="auto">按需检索</option>
                            </select>
                        </div>
                        <button
                            className="home-send"
                            aria-label="发送研究任务"
                            disabled={!prompt.trim() || busy}
                        >
                            {busy ? <Spinner /> : <ArrowUp size={18} />}
                        </button>
                    </div>
                </form>
            </section>
            <div className="dashboard-columns">
                <section className="dashboard-panel">
                    <div className="section-heading">
                        <h2>文献</h2>
                        <button className="text-button" onClick={onImport}>
                            <Plus size={14} />
                            导入
                        </button>
                    </div>
                    {bundle.sources.length ? (
                        bundle.sources.slice(0, 8).map((source) => (
                            <button
                                className="dashboard-row"
                                key={source.id}
                                onClick={() => onSource(source)}
                            >
                                <span>
                                    <strong>{source.title}</strong>
                                    <small>
                                        {source.year || "—"}
                                        {source.doi ? ` · ${source.doi}` : ""}
                                    </small>
                                </span>
                                <ArrowUpRight size={14} />
                            </button>
                        ))
                    ) : (
                        <p className="plain-empty">暂无文献</p>
                    )}
                </section>
                <section className="dashboard-panel">
                    <div className="section-heading">
                        <h2>最近记录</h2>
                        <span className="muted small">
                            {bundle.records.length}
                        </span>
                    </div>
                    {bundle.overview.recent.length ? (
                        bundle.overview.recent.slice(0, 8).map((record) => (
                            <button
                                className="dashboard-row"
                                key={record.id}
                                onClick={() => onRecord(record)}
                            >
                                <span>
                                    <strong>{record.title}</strong>
                                    <small>
                                        {kindLabels[record.kind] || record.kind}{" "}
                                        · v{record.revision} ·{" "}
                                        {date(record.updated_at)}
                                    </small>
                                </span>
                                <ArrowUpRight size={14} />
                            </button>
                        ))
                    ) : (
                        <p className="plain-empty">暂无记录</p>
                    )}
                </section>
            </div>
        </div>
    );
}
