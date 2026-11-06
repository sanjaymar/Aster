import {
    Check,
    ChevronRight,
    FolderPlus,
    PanelRightClose,
    PanelRightOpen,
    Search,
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
import Assistant from "./features/assistant/Assistant";

import { RecordsPage } from "./features/documents/RecordsPage";

import { LiteratureMap } from "./features/library/LiteratureMap";
import { SlidesPage } from "./features/slides/SlidesPage";
import { SlideEditor } from "./features/slides/SlideEditor";
import { LibraryPage } from "./features/library/LibraryPage";

import { Login } from "./features/settings/Login";
import { ModelSettings } from "./features/settings/ModelSettings";
import { TrashDialog } from "./features/settings/TrashDialog";
import { ResearchHome, type ResearchTask } from "./features/workspace/Home";
import { ImportForm, ProjectForm } from "./features/workspace/ProjectDialogs";
import { Sidebar } from "./layout/Sidebar";
import {
    api,
    emptyBundle,
    send,
    type Asset,
    type Bundle,
    type Evidence,
    type ModelState,
    type Project,
    type RecordItem,
    type Run,
    type Source,
} from "./shared/api";
import { EvidenceModal, Modal, Spinner } from "./shared/components";
import type { EditorState } from "./shared/types";

const PaperReader = lazy(() =>
    import("./features/library/PaperReader").then((module) => ({
        default: module.PaperReader,
    })),
);
const DocumentEditor = lazy(() =>
    import("./features/documents/DocumentEditor").then((module) => ({
        default: module.DocumentEditor,
    })),
);
const CsvView = lazy(() =>
    import("./shared/CsvView").then((module) => ({
        default: module.CsvView,
    })),
);

export default function App() {
    const [session, setSession] = useState<{
            required: boolean;
            authenticated: boolean;
        } | null>(null),
        [projects, setProjects] = useState<Project[]>([]),
        [projectId, setProjectId] = useState(""),
        [bundle, setBundle] = useState<Bundle>(emptyBundle),
        [page, setPage] = useState("overview"),
        [loading, setLoading] = useState(false),
        [model, setModel] = useState<ModelState | null>(null);
    const [error, setError] = useState(""),
        [toast, setToast] = useState(""),
        [assistant, setAssistant] = useState(false),
        [sourceIds, setSourceIds] = useState<string[]>([]),
        [artifactIds, setArtifactIds] = useState<string[]>([]),
        [initialRun, setInitialRun] = useState<Run | null>(null),
        [resetSignal, setResetSignal] = useState(0);
    const [trashOpen, setTrashOpen] = useState(false);
    const [projectModal, setProjectModal] = useState(false),
        [editingProject, setEditingProject] = useState<Project>(),
        [importModal, setImportModal] = useState(false),
        [reader, setReader] = useState<Source | null>(null),
        [editor, setEditor] = useState<EditorState | null>(null),
        [evidence, setEvidence] = useState<Evidence | null>(null),
        [csv, setCsv] = useState<Asset | null>(null);
    const [query, setQuery] = useState(""),
        [results, setResults] = useState<Array<{
            kind: string;
            id: string;
            title: string;
            excerpt: string;
        }> | null>(null);
    const restoreRef = useRef<HTMLInputElement>(null),
        activeProject = useRef(projectId);
    activeProject.current = projectId;
    const project = projects.find((project) => project.id === projectId);
    const report = useCallback((message: string) => {
        setError(message);
        window.dispatchEvent(
            new CustomEvent("zhixu:error", { detail: message }),
        );
    }, []);
    const notify = useCallback((message: string) => {
        setToast(message);
        setTimeout(() => setToast(""), 3000);
    }, []);
    const loadProjects = useCallback(async (prefer?: string) => {
        const items = await api<Project[]>("/projects");
        setProjects(items);
        setProjectId((current) => {
            const desired =
                prefer ||
                current ||
                localStorage.getItem("zhixu-selected-project");
            return items.some((p) => p.id === desired)
                ? desired!
                : items[0]?.id || "";
        });
    }, []);
    const refresh = useCallback(async () => {
        if (!projectId) return;
        const base = `/projects/${projectId}`;
        try {
            const [sources, records, conversations, overview, runs] =
                await Promise.all([
                    api<Bundle["sources"]>(base + "/sources"),
                    api<Bundle["records"]>(base + "/artifacts"),
                    api<Bundle["conversations"]>(base + "/conversations"),
                    api<Bundle["overview"]>(base + "/overview"),
                    api<Bundle["runs"]>(base + "/runs?active_only=true"),
                ]);
            if (activeProject.current === projectId)
                setBundle({
                    sources,
                    records,
                    conversations,
                    overview,
                    runs,
                });
        } catch (error) {
            if (activeProject.current === projectId)
                report((error as Error).message);
        }
    }, [projectId, report]);
    const refreshDocuments = useCallback(async () => {
        if (!projectId) return;
        try {
            const [records, overview, conversations] = await Promise.all([
                api<Bundle["records"]>(`/projects/${projectId}/artifacts`),
                api<Bundle["overview"]>(`/projects/${projectId}/overview`),
                api<Bundle["conversations"]>(
                    `/projects/${projectId}/conversations`,
                ),
            ]);
            if (activeProject.current === projectId)
                setBundle((bundle) => ({
                    ...bundle,
                    records,
                    overview,
                    conversations,
                }));
        } catch (error) {
            report((error as Error).message);
        }
    }, [projectId, report]);
    useEffect(() => {
        void api<{ required: boolean; authenticated: boolean }>("/session")
            .then(setSession)
            .catch((error) => report(error.message));
    }, []);
    useEffect(() => {
        if (!session?.authenticated) return;
        void loadProjects().catch((error) => report(error.message));
        void api<ModelState>("/model")
            .then(setModel)
            .catch((error) => report(error.message));
    }, [session?.authenticated]);
    useEffect(() => {
        if (!projectId) return;
        localStorage.setItem("zhixu-selected-project", projectId);
        setBundle(emptyBundle);
        setInitialRun(null);
        setEditor(null);
        setReader(null);
        setSourceIds([]);
        setArtifactIds([]);
        setLoading(true);
        void refresh().finally(() => setLoading(false));
    }, [projectId, refresh]);
    function navigate(next: string) {
        setEditor(null);
        setPage(next);
        if (next === "assistant") setAssistant(true);
    }
    function openRecord(record: RecordItem) {
        setEditor({ kind: record.kind, record });
    }
    async function openEvidence(kind: string, id: string) {
        try {
            setEvidence(
                await api<Evidence>(
                    `/projects/${projectId}/evidence/${kind}/${id}`,
                ),
            );
        } catch (error) {
            report((error as Error).message);
        }
    }
    function newChat() {
        setEditor(null);
        setInitialRun(null);
        setResetSignal((value) => value + 1);
        setAssistant(true);
        setPage("assistant");
    }
    async function startResearch(task: ResearchTask) {
        const run = await api<Run>(
            `/projects/${projectId}/runs`,
            send("POST", {
                prompt: task.prompt,
                mode: task.mode,
                source_ids: task.sourceIds || sourceIds,
                artifact_ids: task.artifactIds || artifactIds,
                retrieval_scope: task.scope,
                response_style: task.responseStyle,
                engine: "pipeline",
                skill_id: task.skillId || null,
                model_profile_id: task.modelId || null,
            }),
        );
        if (activeProject.current !== projectId) return;
        setInitialRun(run);
        setAssistant(true);
        setPage("assistant");
        void refreshDocuments();
    }
    async function restore(file: File) {
        const form = new FormData();
        form.append("file", file);
        setLoading(true);
        try {
            const row = await api<Project>("/restore", {
                method: "POST",
                body: form,
            });
            await loadProjects(row.id);
            notify("项目已恢复");
        } catch (error) {
            report((error as Error).message);
        } finally {
            setLoading(false);
            if (restoreRef.current) restoreRef.current.value = "";
        }
    }
    async function search(event: React.FormEvent) {
        event.preventDefault();
        if (!projectId || !query.trim()) return;
        try {
            setResults(
                await api(
                    `/projects/${projectId}/search?q=${encodeURIComponent(query)}`,
                ),
            );
        } catch (error) {
            report((error as Error).message);
        }
    }
    const closeAssistant = () => {
        setAssistant(false);
        if (page === "assistant") setPage("overview");
    };
    if (session && !session.authenticated)
        return (
            <Login
                onLoggedIn={() =>
                    setSession({ required: true, authenticated: true })
                }
                onError={report}
                error={error}
            />
        );
    if (!session)
        return (
            <div className="boot">
                <h1>Aster</h1>
                <Spinner />
                {error && <p>{error}</p>}
            </div>
        );
    return (
        <div
            className={`app ${page === "overview" ? "is-home" : ""} ${page === "assistant" && !editor ? "is-conversation" : ""} ${assistant && project && !["overview", "assistant"].includes(page) ? "has-assistant" : ""}`}
        >
            <Sidebar
                projects={projects}
                project={project}
                projectId={projectId}
                page={page}
                sourcesCount={bundle.sources.length}
                onNavigate={navigate}
                onSelect={(id) => {
                    setProjectId(id);
                    setPage("overview");
                }}
                onNew={() => {
                    setEditingProject(undefined);
                    setProjectModal(true);
                }}
                onRestore={() => restoreRef.current?.click()}
                onChat={newChat}
                onTrash={() => setTrashOpen(true)}
            />
            <input
                ref={restoreRef}
                hidden
                type="file"
                accept=".zip"
                onChange={(event) => {
                    if (event.target.files?.[0])
                        void restore(event.target.files[0]);
                }}
            />
            <div className="workspace">
                <header className="topbar">
                    <div className="breadcrumb">
                        <span>项目</span>
                        <ChevronRight size={13} />
                        <strong>{project?.title || "Aster"}</strong>
                    </div>
                    <div className="topbar-actions">
                        {project && (
                            <form className="search-box" onSubmit={search}>
                                <Search size={15} />
                                <input
                                    aria-label="搜索项目材料"
                                    placeholder="搜索"
                                    value={query}
                                    onChange={(e) => setQuery(e.target.value)}
                                    maxLength={200}
                                />
                            </form>
                        )}
                        <button
                            className={`model-pill ${model?.connected ? "connected" : ""}`}
                            onClick={() => navigate("settings")}
                        >
                            <span className="status-dot" />
                            {model?.config.name ||
                                (model?.connected
                                    ? model.selected
                                    : "连接模型")}
                        </button>
                        {project && (
                            <button
                                className="icon-button"
                                aria-label={assistant ? "收起助手" : "打开助手"}
                                onClick={() => {
                                    if (page === "assistant") closeAssistant();
                                    else if (page === "overview") {
                                        setAssistant(true);
                                        setPage("assistant");
                                    } else setAssistant((value) => !value);
                                }}
                            >
                                {assistant ? (
                                    <PanelRightClose size={19} />
                                ) : (
                                    <PanelRightOpen size={19} />
                                )}
                            </button>
                        )}
                    </div>
                </header>
                <main className={`main-content ${editor ? "is-document" : ""}`}>
                    {page === "settings" ? (
                        <ModelSettings
                            model={model}
                            onUpdate={setModel}
                            onError={report}
                            notify={notify}
                        />
                    ) : !project ? (
                        <div className="onboarding">
                            <h1>Aster</h1>
                            <button
                                className="button primary"
                                onClick={() => setProjectModal(true)}
                            >
                                <FolderPlus size={17} />
                                创建项目
                            </button>
                            <button
                                className="text-button"
                                onClick={() => restoreRef.current?.click()}
                            >
                                恢复备份
                            </button>
                        </div>
                    ) : loading ? (
                        <div className="loading-state">
                            <Spinner />
                        </div>
                    ) : editor?.record?.kind === "deck" ? (
                        <SlideEditor
                            projectId={projectId}
                            record={editor.record}
                            onClose={() => setEditor(null)}
                            onSaved={() => void refreshDocuments()}
                            onError={report}
                            onEvidence={openEvidence}
                        />
                    ) : editor ? (
                        <Suspense fallback={<Spinner />}>
                            <DocumentEditor
                                key={editor.record?.id || `new-${editor.kind}`}
                                projectId={projectId}
                                record={editor.record}
                                kind={editor.kind}
                                initialContent={editor.content}
                                initialTitle={editor.title}
                                initialFields={editor.fields}
                                sources={bundle.sources}
                                records={bundle.records}
                                onSaved={() => void refreshDocuments()}
                                onEvidence={openEvidence}
                                onClose={() => setEditor(null)}
                                onError={report}
                                onCsv={setCsv}
                            />
                        </Suspense>
                    ) : (
                        <>
                            {page === "overview" && (
                                <ResearchHome
                                    project={project}
                                    bundle={bundle}
                                    selectedCount={
                                        sourceIds.length + artifactIds.length
                                    }
                                    onStart={startResearch}
                                    onError={report}
                                    onImport={() => setImportModal(true)}
                                    onNote={() => setEditor({ kind: "note" })}
                                    onMap={() => setPage("map")}
                                    onSlides={() => setPage("slides")}
                                    onEdit={() => {
                                        setEditingProject(project);
                                        setProjectModal(true);
                                    }}
                                    onRecord={openRecord}
                                    onSource={setReader}
                                />
                            )}
                            {page === "library" && (
                                <LibraryPage
                                    projectId={projectId}
                                    bundle={bundle}
                                    sourceIds={sourceIds}
                                    setSourceIds={setSourceIds}
                                    setImportModal={setImportModal}
                                    setReader={setReader}
                                    onRefresh={() => void refresh()}
                                    onError={report}
                                />
                            )}
                            {page === "notes" && (
                                <RecordsPage
                                    bundle={bundle}
                                    artifactIds={artifactIds}
                                    setArtifactIds={setArtifactIds}
                                    setEditor={setEditor}
                                    openRecord={openRecord}
                                    onStart={startResearch}
                                    onError={report}
                                />
                            )}
                            {page === "map" && (
                                <LiteratureMap
                                    projectId={projectId}
                                    sources={bundle.sources}
                                    records={bundle.records}
                                    onOpen={setReader}
                                    onRecord={openRecord}
                                    onNote={(s) => { void startResearch({prompt:"为这篇论文生成结构完整的精读报告，包含研究问题、方法与数据、结果、局限及待追问问题。",mode:"reading",scope:"selected",responseStyle:"grounded",sourceIds:[s.id],skillId:"paper-reading"}).catch(e=>report(e.message)); }}
                                    onSlides={(s) => {setSourceIds([s.id]);navigate("slides");}}
                                    onError={report}
                                />
                            )}
                            {page === "slides" && (
                                <SlidesPage
                                    projectId={projectId}
                                    bundle={bundle}
                                    initialSources={sourceIds}
                                    onOpen={openRecord}
                                    onStart={startResearch}
                                    onError={report}
                                    onRefresh={() => void refreshDocuments()}
                                />
                            )}
                        </>
                    )}
                </main>
            </div>
            {(assistant || page === "assistant") && project && (
                <Assistant
                    key={projectId}
                    initialRun={initialRun}
                    resetSignal={resetSignal}
                    presentation={page === "assistant" ? "canvas" : "panel"}
                    projectId={projectId}
                    bundle={bundle}
                    sourceIds={sourceIds}
                    setSourceIds={setSourceIds}
                    artifactIds={artifactIds}
                    setArtifactIds={setArtifactIds}
                    defaultMode="chat"
                    onError={report}
                    onRefresh={() => void refreshDocuments()}
                    onEvidence={openEvidence}
                    onClose={closeAssistant}
                />
            )}
            {error && (
                <div className="global-error" role="alert">
                    <span>{error}</span>
                    <button
                        className="icon-button"
                        aria-label="关闭错误"
                        onClick={() => setError("")}
                    >
                        <X size={15} />
                    </button>
                </div>
            )}
            {toast && (
                <div className="toast" role="status">
                    <Check size={15} />
                    {toast}
                </div>
            )}
            {projectModal && (
                <ProjectForm
                    project={editingProject}
                    onClose={() => setProjectModal(false)}
                    onError={report}
                    onDeleted={async () => {
                        setProjectModal(false);
                        setPage("overview");
                        await loadProjects();
                    }}
                    onSaved={async (row) => {
                        await loadProjects(row.id);
                        setProjectModal(false);
                    }}
                />
            )}
            {importModal && project && (
                <ImportForm
                    projectId={projectId}
                    onClose={() => setImportModal(false)}
                    onError={report}
                    onSaved={() => {
                        setImportModal(false);
                        void refresh();
                    }}
                />
            )}
            {reader && (
                <Suspense fallback={<Spinner />}>
                    <PaperReader
                        key={reader.id}
                        source={reader}
                        projectId={projectId}
                        bundle={bundle}
                        onClose={() => setReader(null)}
                        onOpenNote={(note) => {
                            setReader(null);
                            openRecord(note);
                        }}
                        onError={report}
                        onRefresh={() => void refresh()}
                        onEvidence={openEvidence}
                    />
                </Suspense>
            )}
            {evidence && (
                <EvidenceModal
                    item={evidence}
                    onClose={() => setEvidence(null)}
                />
            )}
            {csv && (
                <Suspense fallback={<Spinner />}>
                    <CsvView
                        projectId={projectId}
                        asset={csv}
                        onClose={() => setCsv(null)}
                        onError={report}
                    />
                </Suspense>
            )}
            {results && (
                <Modal
                    title={`搜索：${query}`}
                    onClose={() => setResults(null)}
                    wide
                >
                    {results.length ? (
                        results.map((result) => (
                            <button
                                key={result.id}
                                className="search-result"
                                onClick={() =>
                                    void openEvidence(result.kind, result.id)
                                }
                            >
                                <strong>{result.title}</strong>
                                <p>{result.excerpt}</p>
                            </button>
                        ))
                    ) : (
                        <p className="plain-empty">无匹配结果</p>
                    )}
                </Modal>
            )}
            {trashOpen && (
                <TrashDialog
                    projectId={projectId}
                    onClose={() => setTrashOpen(false)}
                    onRefresh={async () => {
                        await loadProjects();
                        await refresh();
                    }}
                    onError={report}
                />
            )}
        </div>
    );
}
