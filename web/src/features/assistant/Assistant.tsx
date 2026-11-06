import {
    ArrowUp,
    BookOpen,
    Check,
    ChevronDown,
    History,
    Plus,
    Sparkles,
    Square,
    X,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import {
    api,
    send,
    type Bundle,
    type ChatMessage,
    type Run,
} from "../../shared/api";
import { MarkdownView, Spinner, statusLabels } from "../../shared/components";
import { ConversationHistory } from "./ConversationHistory";
import { AssistantOptions, useAssistantOptions } from "./AssistantOptions";

type Props = {
    initialRun?: Run | null;
    pinnedDocument?: boolean;
    draftQuestion?: { text: string; key: number };
    initialScope?: "selected" | "project";
    sourceVersionIds?: string[];
    resetSignal?: number;
    presentation?: "panel" | "canvas";
    projectId: string;
    bundle: Bundle;
    sourceIds: string[];
    setSourceIds: (v: string[]) => void;
    artifactIds: string[];
    setArtifactIds: (v: string[]) => void;
    defaultMode: string;
    onError: (s: string) => void;
    onRefresh: () => void;
    onEvidence: (k: string, id: string) => void;
    onClose: () => void;
};
export default function Assistant({
    initialRun,
    pinnedDocument = false,
    draftQuestion,
    initialScope = "project",
    sourceVersionIds = [],
    resetSignal = 0,
    presentation = "panel",
    projectId,
    bundle,
    sourceIds,
    setSourceIds,
    artifactIds,
    setArtifactIds,
    defaultMode,
    onError,
    onRefresh,
    onEvidence,
    onClose,
}: Props) {
    const promptId = useId();
    const [input, setInput] = useState(""),
        [mode, setMode] = useState(defaultMode),
        [responseStyle, setResponseStyle] = useState(
            pinnedDocument ? "grounded" : "discussion",
        ),
        [conversation, setConversation] = useState<string | null>(null),
        [messages, setMessages] = useState<ChatMessage[]>([]),
        [run, setRun] = useState<Run | null>(null),
        [partial, setPartial] = useState(""),
        [busy, setBusy] = useState(false),
        [activity, setActivity] = useState(""),
        [engine] = useState("assistant"),
        [scope, setScope] = useState(initialScope),
        [showHistory, setShowHistory] = useState(false);
    const live = !!run && ["queued", "running"].includes(run.status);
    const options = useAssistantOptions(pinnedDocument);
    const end = useRef<HTMLDivElement>(null);
    const activeProject = useRef(projectId);
    const loadTicket = useRef(0);
    activeProject.current = projectId;
    useEffect(() => setMode(defaultMode), [defaultMode]);
    useEffect(() => {
        if (draftQuestion) setInput(draftQuestion.text);
    }, [draftQuestion?.key]);
    useEffect(() => {
        loadTicket.current++;
        setInput("");
        setConversation(null);
        setRun(null);
        setMessages([]);
        setPartial("");
        setActivity("");
    }, [resetSignal]);
    async function loadConversation(id: string) {
        const ticket = ++loadTicket.current;
        const scope = projectId;
        try {
            const rows = await api<ChatMessage[]>(
                `/projects/${projectId}/conversations/${id}`,
            );
            if (
                activeProject.current === scope &&
                loadTicket.current === ticket
            )
                setMessages(rows);
        } catch (e) {
            if (
                activeProject.current === scope &&
                loadTicket.current === ticket
            )
                onError((e as Error).message);
        }
    }
    useEffect(() => {
        loadTicket.current++;
        setMessages([]);
        setConversation(null);
        setRun(null);
        setPartial("");
    }, [projectId]);
    useEffect(() => {
        if (!pinnedDocument) return;
        loadTicket.current++;
        setMessages([]);
        setConversation(null);
        setRun(null);
        setPartial("");
    }, [sourceVersionIds.join("|")]);
    useEffect(() => {
        if (
            !initialRun ||
            initialRun.id === run?.id ||
            (initialRun.project_id && initialRun.project_id !== projectId)
        )
            return;
        setConversation(initialRun.conversation_id);
        setRun(initialRun);
        const snapshot = initialRun.context?.corpus_snapshot as
            { scope?: string } | undefined;
        if (snapshot?.scope === "project" || snapshot?.scope === "selected")
            setScope(snapshot.scope);
        setMode(initialRun.mode);
        setResponseStyle(
            String(initialRun.context?.response_style || "grounded"),
        );

        setPartial("");
        void loadConversation(initialRun.conversation_id);
    }, [initialRun?.id]);

    useEffect(() => {
        if (!run && conversation) {
            const active = bundle.runs.find(
                (r) =>
                    ["running", "queued"].includes(r.status) &&
                    r.conversation_id === conversation,
            );
            if (active) {
                setRun(active);
            }
        }
    }, [bundle.runs, run, conversation]);
    useEffect(() => {
        if (conversation) void loadConversation(conversation);
    }, [conversation]);
    useEffect(() => {
        if (!run || !["queued", "running"].includes(run.status)) return;
        let disposed = false;
        const events = new EventSource(`/api/runs/${run.id}/events`);
        setPartial("");
        setActivity("正在准备材料…");
        events.onmessage = (event) => {
            const item = JSON.parse(event.data);
            const d = item.payload;
            if (item.kind === "text") setPartial((t) => t + d.text);
            if (item.kind === "answer_verified") setPartial(d.text);
            if (item.kind === "stage_start")
                setActivity(
                    ((
                        {
                            Guardrails: "检查资料范围",
                            NLU: "理解问题与指代",
                            Retrieve: "检索证据",
                            Rerank: "筛选证据",
                            Reflect: "核对证据充分性",
                            Generate: "生成并核对主张",
                            Memory: "完成回答",
                        } as Record<string, string>
                    )[d.name] || d.name) + (d.attempt > 1 ? " · 补充检索" : ""),
                );
            if (item.kind === "turn") setActivity("正在整理回答");
            if (item.kind === "tool_start")
                setActivity(
                    (
                        {
                            read_evidence: "正在读取依据",
                            search_materials: "正在检索材料",
                            save_draft: "正在保存草稿",
                            search_knowledge: "正在检索知识库",
                            list_papers: "正在查找文献",
                            load_skill: "正在加载 Skill",
                        } as Record<string, string>
                    )[d.name] || "正在使用工具",
                );
            if (item.kind === "tool_end")
                setActivity(
                    d.ok ? "材料已处理，继续分析…" : "正在调整处理方式…",
                );
            if (item.kind === "artifact") onRefresh();
        };
        const finish = async () => {
            events.close();
            try {
                const next = await api<Run>("/runs/" + run.id);
                if (disposed) return;
                setRun(next);
                setActivity(statusLabels[next.status] || next.status);
                await loadConversation(next.conversation_id);
                if (next.error) onError(next.error);
                onRefresh();
            } catch (e) {
                if (!disposed) onError((e as Error).message);
            }
        };
        events.addEventListener("finished", finish);
        events.onerror = () => {
            if (events.readyState === EventSource.CLOSED) void finish();
        };
        return () => {
            disposed = true;
            events.close();
        };
    }, [run?.id, run?.status]);
    useEffect(() => {
        const messages = end.current?.parentElement;
        messages?.scrollTo({ top: messages.scrollHeight, behavior: "smooth" });
    }, [messages.length, partial]);
    async function submit() {
        if (!input.trim() || live || busy) return;
        setBusy(true);
        try {
            const prompt = input;
            const r = await api<Run>(
                `/projects/${projectId}/runs`,
                send("POST", {
                    prompt,
                    mode,
                    conversation_id: conversation,
                    source_ids: sourceIds,
                    source_version_ids:
                        scope === "selected" ? sourceVersionIds : [],
                    artifact_ids: artifactIds,
                    engine,
                    response_style: responseStyle,
                    retrieval_scope: scope,
                    model_profile_id: options.modelId || null,
                    skill_id: options.skillId || null,
                }),
            );
            if (activeProject.current !== projectId) return;
            setInput("");
            setConversation(r.conversation_id);
            setMessages((m) => [
                ...m,
                { id: r.id, role: "user", content: prompt },
            ]);
            setRun(r);
            onRefresh();
        } catch (e) {
            onError((e as Error).message);
        } finally {
            setBusy(false);
        }
    }
    async function cancel() {
        if (!run) return;
        try {
            await api("/runs/" + run.id + "/cancel", send("POST", {}));
            setActivity("正在取消，已完成的记录会保留…");
        } catch (e) {
            onError((e as Error).message);
        }
    }
    function toggle(id: string, list: string[], setter: (v: string[]) => void) {
        setter(
            list.includes(id) ? list.filter((v) => v !== id) : [...list, id],
        );
    }
    return (
        <aside
            className={`assistant ${presentation === "canvas" ? "assistant-canvas" : ""}`}
        >
            <header className="assistant-head">
                <div className="inline">
                    <span className="assistant-orb">
                        <Sparkles size={16} />
                    </span>
                    <h2>Aster助手</h2>
                </div>
                <div className="inline">
                    <button
                        className="icon-button"
                        aria-label="查看对话"
                        disabled={live}
                        onClick={() => setShowHistory(!showHistory)}
                    >
                        <History size={16} />
                    </button>
                    <button
                        className="icon-button"
                        aria-label="新对话"
                        disabled={live}
                        onClick={() => {
                            loadTicket.current++;
                            setConversation(null);
                            setRun(null);
                            setMessages([]);
                            setPartial("");
                            setActivity("");
                        }}
                    >
                        <Plus size={17} />
                    </button>
                    <button
                        className="icon-button assistant-mobile-close"
                        aria-label="关闭助手"
                        onClick={onClose}
                    >
                        <X size={17} />
                    </button>
                </div>
            </header>
            {showHistory && (
                <ConversationHistory
                    projectId={projectId}
                    items={bundle.conversations}
                    onSelect={(id) => {
                        setConversation(id);
                        setPartial("");
                        setRun(null);
                        setShowHistory(false);
                    }}
                    onDeleted={(id) => {
                        if (id === conversation) {
                            setConversation(null);
                            setMessages([]);
                            setRun(null);
                            setPartial("");
                        }
                    }}
                    onRefresh={onRefresh}
                    onError={onError}
                />
            )}
            {!pinnedDocument && (
                <details className="material-picker">
                    <summary>
                        <BookOpen size={14} />
                        <span>
                            {scope === "project"
                                ? "本项目资料"
                                : `已选 ${sourceIds.length + artifactIds.length} 份材料`}
                        </span>
                        <ChevronDown size={14} />
                    </summary>
                    <div className="material-options">
                        <label className="field">
                            <span>检索范围</span>
                            <select
                                aria-label="检索范围"
                                value={scope}
                                onChange={(e) =>
                                    setScope(
                                        e.target.value as
                                            "selected" | "project",
                                    )
                                }
                            >
                                <option value="selected">
                                    仅本次选中的材料
                                </option>
                                <option value="project">
                                    本项目全部资料与记录
                                </option>
                            </select>
                        </label>
                        <p className="muted small">
                            {scope === "project"
                                ? "按需检索本项目资料。"
                                : "仅使用选中的材料。"}
                        </p>
                        {bundle.sources.map((s) => (
                            <label key={s.id}>
                                <input
                                    type="checkbox"
                                    checked={sourceIds.includes(s.id)}
                                    onChange={() =>
                                        toggle(s.id, sourceIds, setSourceIds)
                                    }
                                />
                                <span>{s.title}</span>
                            </label>
                        ))}
                        {bundle.records.map((a) => (
                            <label key={a.id}>
                                <input
                                    type="checkbox"
                                    checked={artifactIds.includes(a.id)}
                                    onChange={() =>
                                        toggle(
                                            a.id,
                                            artifactIds,
                                            setArtifactIds,
                                        )
                                    }
                                />
                                <span>
                                    {a.title} · v{a.revision}
                                </span>
                            </label>
                        ))}
                        {!bundle.sources.length && !bundle.records.length && (
                            <p className="muted small">
                                导入资料或创建记录后，可以在这里选择。
                            </p>
                        )}
                    </div>
                </details>
            )}
            <div className="assistant-messages" aria-live="polite">
                {!messages.length && !live && (
                    <div className="assistant-welcome">
                        <h3>新对话</h3>
                        <div className="suggestions">
                            {[
                                "帮我梳理选中文献的研究问题与方法",
                                "检查实验方案还有哪些遗漏",
                                "根据所选记录拟一个讨论提纲",
                            ].map((s) => (
                                <button key={s} onClick={() => setInput(s)}>
                                    {s}
                                    <ArrowUp size={13} />
                                </button>
                            ))}
                        </div>
                    </div>
                )}
                {messages.map((m) => (
                    <article
                        key={m.id}
                        className={
                            "chat-message " +
                            (m.role === "user" ? "user" : "assistant-message")
                        }
                    >
                        <span className="message-author">
                            {m.role === "user" ? "你" : "Aster"}
                        </span>
                        <MarkdownView
                            text={m.content}
                            onEvidence={onEvidence}
                        />
                    </article>
                ))}
                {live && (
                    <article className="chat-message assistant-message">
                        <span className="message-author">Aster</span>
                        {partial ? (
                            <MarkdownView
                                text={partial}
                                onEvidence={onEvidence}
                            />
                        ) : (
                            <div className="inline muted">
                                <Spinner />
                                <span>正在等待模型…</span>
                            </div>
                        )}
                    </article>
                )}
                {!live && run && run.status !== "completed" && partial && (
                    <article className="chat-message">
                        <span className="message-author">未完成的输出</span>
                        <MarkdownView text={partial} onEvidence={onEvidence} />
                    </article>
                )}
                <div ref={end} />
            </div>
            <div className="assistant-compose">
                <AssistantOptions
                    options={options}
                    reader={pinnedDocument}
                    disabled={live || busy}
                />
                {activity && (
                    <div className="activity-line">
                        {live ? <Spinner /> : <Check size={13} />}
                        <span>{activity}</span>
                    </div>
                )}
                <label className="sr-only" htmlFor={promptId}>
                    给Aster的任务
                </label>
                <textarea
                    id={promptId}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="输入问题…"
                    onKeyDown={(e) => {
                        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                            e.preventDefault();
                            void submit();
                        }
                    }}
                />
                <div className="compose-footer">
                    <select
                        aria-label="回答方式"
                        value={responseStyle}
                        onChange={(e) => setResponseStyle(e.target.value)}
                    >
                        <option value="grounded">依据资料</option>
                        <option value="discussion">自由讨论</option>
                    </select>
                    <select
                        aria-label="助手任务类型"
                        value={mode}
                        onChange={(e) => setMode(e.target.value)}
                    >
                        <option value="chat">仅对话</option>
                        <option value="reading">保存为笔记</option>
                        <option value="plan">推敲方案</option>
                        <option value="writing">保存为草稿</option>
                    </select>
                    {live ? (
                        <button
                            className="send-button stop"
                            onClick={cancel}
                            aria-label="停止任务"
                        >
                            <Square size={14} />
                        </button>
                    ) : (
                        <button
                            className="send-button"
                            onClick={submit}
                            disabled={!input.trim() || busy}
                            aria-label="发送任务"
                        >
                            {busy ? <Spinner /> : <ArrowUp size={19} />}
                        </button>
                    )}
                </div>
                <p className="compose-hint">
                    {options.selected?.name || "模型"} · Ctrl / ⌘ + Enter
                </p>
            </div>
        </aside>
    );
}
