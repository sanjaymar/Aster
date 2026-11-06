import { FolderPlus, Upload } from "lucide-react";
import { useState } from "react";
import { api, send, type Project } from "../../shared/api";
import { Field, Modal, Spinner } from "../../shared/components";
import { DeleteButton } from "../../shared/DeleteButton";

export function ProjectForm({
    project,
    onClose,
    onSaved,
    onError,
    onDeleted,
}: {
    project?: Project;
    onClose: () => void;
    onSaved: (p: Project) => void;
    onError: (s: string) => void;
    onDeleted: () => void | Promise<void>;
}) {
    const [title, setTitle] = useState(project?.title || ""),
        [description, setDescription] = useState(project?.description || ""),
        [domain, setDomain] = useState(project?.domain || "research"),
        [knowledge, setKnowledge] = useState({
            subject: project?.knowledge?.subject || "",
            terminology: project?.knowledge?.terminology || "",
            instructions: project?.knowledge?.instructions || "",
            language: project?.knowledge?.language || "zh",
        }),
        [busy, setBusy] = useState(false);
    return (
        <Modal title={project ? "编辑项目" : "创建一个项目"} onClose={onClose}>
            <form
                onSubmit={async (e) => {
                    e.preventDefault();
                    setBusy(true);
                    try {
                        onSaved(
                            await api<Project>(
                                "/projects" + (project ? "/" + project.id : ""),
                                send(project ? "PUT" : "POST", {
                                    title,
                                    description,
                                    domain,
                                    knowledge,
                                }),
                            ),
                        );
                    } catch (e) {
                        onError((e as Error).message);
                    } finally {
                        setBusy(false);
                    }
                }}
            >
                <Field label="项目名称">
                    <input
                        value={title}
                        autoFocus
                        onChange={(e) => setTitle(e.target.value)}
                        placeholder="例如：一个研究问题、论文课题或学习方向"
                        maxLength={200}
                        required
                    />
                </Field>
                <Field label="想解决的问题">
                    <textarea
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        placeholder="你的目标、目前的疑问，以及希望得到的产出。"
                    />
                </Field>
                <Field
                    label="项目领域"
                    hint="领域决定可用的记录类型。基础资料、笔记与写作能力通用。"
                >
                    <select
                        disabled={!!project}
                        value={domain}
                        onChange={(e) => setDomain(e.target.value)}
                    >
                        <option value="research">
                            科研研究 · 文献、实验与论文
                        </option>
                        <option value="general">
                            通用知识 · 资料、笔记与报告
                        </option>
                    </select>
                </Field>
                <Field label="知识库主题">
                    <div className="inline">
                        <input
                            aria-label="知识库主题"
                            value={knowledge.subject}
                            maxLength={200}
                            placeholder="代谢组学、机器学习或其他主题"
                            onChange={(e) =>
                                setKnowledge({
                                    ...knowledge,
                                    subject: e.target.value,
                                })
                            }
                        />
                        <button
                            type="button"
                            className="text-button"
                            onClick={() =>
                                setKnowledge({
                                    ...knowledge,
                                    subject: "Metabolomics",
                                    terminology:
                                        "代谢组学 metabolomics；液相色谱质谱 LC-MS；质量控制 QC；代谢物鉴定 metabolite annotation",
                                    instructions:
                                        "讨论代谢组学的方法与研究设计；区分注释等级、关联与因果、方案与已完成结果。",
                                })
                            }
                        >
                            代谢组学预设
                        </button>
                    </div>
                </Field>
                <details className="knowledge-preferences">
                    <summary>术语与助手偏好</summary>
                    <Field label="术语、缩写及别名">
                        <textarea
                            aria-label="知识库术语"
                            value={knowledge.terminology}
                            maxLength={4000}
                            onChange={(e) =>
                                setKnowledge({
                                    ...knowledge,
                                    terminology: e.target.value,
                                })
                            }
                        />
                    </Field>
                    <Field label="回复偏好">
                        <textarea
                            aria-label="助手回复偏好"
                            value={knowledge.instructions}
                            maxLength={6000}
                            onChange={(e) =>
                                setKnowledge({
                                    ...knowledge,
                                    instructions: e.target.value,
                                })
                            }
                        />
                    </Field>
                    <Field label="回答语言">
                        <select
                            value={knowledge.language}
                            onChange={(e) =>
                                setKnowledge({
                                    ...knowledge,
                                    language: e.target.value as "zh" | "en",
                                })
                            }
                        >
                            <option value="zh">中文</option>
                            <option value="en">English</option>
                        </select>
                    </Field>
                </details>
                <footer className="form-footer">
                    {project ? (
                        <DeleteButton
                            path={`/projects/${project.id}`}
                            title={project.title}
                            label="删除项目"
                            onDeleted={onDeleted}
                            onError={onError}
                        />
                    ) : (
                        <span />
                    )}
                    <button
                        className="button primary"
                        disabled={!title.trim() || busy}
                    >
                        {busy ? <Spinner /> : <FolderPlus size={16} />}保存项目
                    </button>
                </footer>
            </form>
        </Modal>
    );
}

export function ImportForm({
    projectId,
    onClose,
    onSaved,
    onError,
}: {
    projectId: string;
    onClose: () => void;
    onSaved: () => void;
    onError: (s: string) => void;
}) {
    const [file, setFile] = useState<File | null>(null),
        [title, setTitle] = useState(""),
        [authors, setAuthors] = useState(""),
        [year, setYear] = useState(""),
        [doi, setDoi] = useState(""),
        [busy, setBusy] = useState(false);
    return (
        <Modal title="导入文献资料" onClose={onClose}>
            <form
                onSubmit={async (e) => {
                    e.preventDefault();
                    if (!file) return;
                    setBusy(true);
                    try {
                        const form = new FormData();
                        form.append("file", file);
                        form.append("title", title);
                        form.append("authors", authors);
                        form.append("year", year);
                        form.append("doi", doi);
                        await api(`/projects/${projectId}/sources`, {
                            method: "POST",
                            body: form,
                        });
                        onSaved();
                    } catch (e) {
                        onError((e as Error).message);
                    } finally {
                        setBusy(false);
                    }
                }}
            >
                <label className="upload-zone">
                    <Upload size={27} />
                    <strong>{file?.name || "选择一篇论文或文档"}</strong>
                    <span>PDF、TXT、Markdown、CSV · 最多 200 MB</span>
                    <input
                        type="file"
                        accept=".pdf,.txt,.md,.csv"
                        onChange={(e) => {
                            const f = e.target.files?.[0] || null;
                            setFile(f);
                            if (f && !title)
                                setTitle(f.name.replace(/\.[^.]+$/, ""));
                        }}
                        required
                    />
                </label>
                <Field label="标题">
                    <input
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        placeholder="留空时使用文件标题"
                        maxLength={500}
                    />
                </Field>
                <div className="form-columns">
                    <Field label="作者">
                        <input
                            value={authors}
                            onChange={(e) => setAuthors(e.target.value)}
                            maxLength={2000}
                        />
                    </Field>
                    <Field label="年份">
                        <input
                            value={year}
                            onChange={(e) => setYear(e.target.value)}
                            maxLength={20}
                        />
                    </Field>
                </div>
                <Field label="DOI（可选）">
                    <input
                        value={doi}
                        onChange={(e) => setDoi(e.target.value)}
                        maxLength={300}
                    />
                </Field>
                <p className="muted small">
                    原始文件和提取文本保存在本地。扫描件可阅读原文，暂不自动识别文字。
                </p>
                <footer className="form-footer">
                    <span />
                    <button className="button primary" disabled={!file || busy}>
                        {busy ? <Spinner /> : <Upload size={16} />}导入资料
                    </button>
                </footer>
            </form>
        </Modal>
    );
}
