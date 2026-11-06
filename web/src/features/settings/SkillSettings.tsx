import { Copy, Download, Plus, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, send, type Skill } from "../../shared/api";
import { Field, Modal } from "../../shared/components";

const empty = {
    name: "",
    description: "",
    instructions: "",
    category: "custom" as const,
    enabled: true,
    source_url: "",
};
const categories: Record<string, string> = {
    reading: "阅读",
    thinking: "思考",
    slides: "汇报",
    custom: "自定义",
};

export function SkillSettings({
    onError,
    notify,
}: {
    onError: (s: string) => void;
    notify: (s: string) => void;
}) {
    const [skills, setSkills] = useState<Skill[]>([]),
        [editing, setEditing] = useState<Partial<Skill> | null>(null),
        [busy, setBusy] = useState(false);
    const file = useRef<HTMLInputElement>(null);
    function refresh() {
        void api<Skill[]>("/skills")
            .then(setSkills)
            .catch((e) => onError(e.message));
        window.dispatchEvent(new Event("aster:skills-updated"));
    }
    useEffect(refresh, []);
    function exportSkill(s: Partial<Skill>) {
        const text = `---\nname: ${JSON.stringify(s.name)}\ndescription: ${JSON.stringify(s.description)}\n---\n\n${s.instructions}\n`;
        const url = URL.createObjectURL(
            new Blob([text], { type: "text/markdown" }),
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = "SKILL.md";
        link.click();
        URL.revokeObjectURL(url);
    }
    return (
        <section className="skills-settings">
            <div className="section-heading">
                <div>
                    <h2>Skills</h2>
                    <p className="muted small">
                        按需加载工作方法。支持自定义指令和
                        SKILL.md；不执行附带脚本。
                    </p>
                </div>
                <div className="inline">
                    <button
                        className="button secondary"
                        onClick={() => file.current?.click()}
                    >
                        <Upload size={15} />
                        导入
                    </button>
                    <button
                        className="button primary"
                        onClick={() => setEditing(empty)}
                    >
                        <Plus size={15} />
                        新建
                    </button>
                </div>
            </div>
            <input
                hidden
                ref={file}
                type="file"
                accept=".md,.txt"
                onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    if (f.size > 32000) {
                        onError("技能文本不能超过 32 KB");
                        return;
                    }
                    const text = await f.text(),
                        header = text.match(
                            /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/,
                        );
                    const scalar = (key: string) => {
                        const value =
                            header?.[1].match(
                                new RegExp(`^${key}:\\s*(.+)$`, "m"),
                            )?.[1] || "";
                        try {
                            return JSON.parse(value);
                        } catch {
                            return value.replace(/^['"]|['"]$/g, "");
                        }
                    };
                    setEditing({
                        ...empty,
                        name: scalar("name") || f.name.replace(/\.md$/, ""),
                        description: scalar("description") || "导入的工作方法",
                        instructions: text
                            .replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, "")
                            .trim()
                            .slice(0, 16000),
                    });
                    e.target.value = "";
                }}
            />
            <div className="skill-grid">
                {skills.map((s) => (
                    <article
                        key={s.id}
                        className={`skill-card ${!s.enabled ? "disabled" : ""}`}
                    >
                        <div className="inline spread">
                            <span className="eyebrow">
                                {categories[s.category]}
                            </span>
                            <span className="muted small">
                                {s.builtin
                                    ? "内置"
                                    : s.enabled
                                      ? "已启用"
                                      : "已停用"}
                            </span>
                        </div>
                        <button
                            className="skill-open"
                            onClick={() => setEditing(s)}
                        >
                            <h3>{s.name}</h3>
                            <p>{s.description}</p>
                            {s.output && <small>产出：{s.output}</small>}
                            {s.requires && <small>输入：{s.requires}</small>}
                        </button>
                        {s.source_url && (
                            <a
                                className="skill-source"
                                href={s.source_url}
                                target="_blank"
                                rel="noreferrer"
                            >
                                开源方法 ↗
                            </a>
                        )}
                        <div className="inline spread">
                            <button
                                className="text-button"
                                onClick={() =>
                                    setEditing({
                                        ...s,
                                        id: undefined,
                                        builtin: false,
                                        name: s.name + " · 自定义",
                                    })
                                }
                            >
                                <Copy size={13} />
                                复制
                            </button>
                            <button
                                className="icon-button"
                                aria-label={"导出 " + s.name}
                                onClick={() => exportSkill(s)}
                            >
                                <Download size={14} />
                            </button>
                        </div>
                    </article>
                ))}
            </div>
            {editing && (
                <Modal
                    title={editing.name || "新建 Skill"}
                    onClose={() => setEditing(null)}
                    wide
                >
                    <form
                        onSubmit={async (e) => {
                            e.preventDefault();
                            setBusy(true);
                            try {
                                const body = Object.fromEntries(
                                    Object.entries(editing).filter(([k]) =>
                                        Object.keys(empty).includes(k),
                                    ),
                                );
                                await api(
                                    `/skills${editing.id ? "/" + editing.id : ""}`,
                                    send(editing.id ? "PUT" : "POST", body),
                                );
                                refresh();
                                setEditing(null);
                                notify("技能已保存");
                            } catch (e) {
                                onError((e as Error).message);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        <Field label="名称">
                            <input
                                required
                                value={editing.name || ""}
                                disabled={editing.builtin}
                                maxLength={100}
                                onChange={(e) =>
                                    setEditing({
                                        ...editing,
                                        name: e.target.value,
                                    })
                                }
                            />
                        </Field>
                        <Field label="用途">
                            <input
                                required
                                value={editing.description || ""}
                                disabled={editing.builtin}
                                maxLength={500}
                                onChange={(e) =>
                                    setEditing({
                                        ...editing,
                                        description: e.target.value,
                                    })
                                }
                            />
                        </Field>
                        <Field label="技能指令">
                            <textarea
                                className="skill-instructions"
                                required
                                value={editing.instructions || ""}
                                disabled={editing.builtin}
                                maxLength={16000}
                                onChange={(e) =>
                                    setEditing({
                                        ...editing,
                                        instructions: e.target.value,
                                    })
                                }
                            />
                        </Field>
                        <Field label="参考来源">
                            <input
                                type="url"
                                value={editing.source_url || ""}
                                disabled={editing.builtin}
                                onChange={(e) =>
                                    setEditing({
                                        ...editing,
                                        source_url: e.target.value,
                                    })
                                }
                            />
                        </Field>
                        {editing.builtin ? (
                            <p className="muted small">
                                {editing.origin}。内置版本可复制后修改。
                            </p>
                        ) : (
                            <label className="check-label">
                                <input
                                    type="checkbox"
                                    checked={editing.enabled}
                                    onChange={(e) =>
                                        setEditing({
                                            ...editing,
                                            enabled: e.target.checked,
                                        })
                                    }
                                />
                                在助手中启用
                            </label>
                        )}
                        <footer className="form-footer">
                            {editing.id && !editing.builtin ? (
                                <button
                                    type="button"
                                    className="text-button danger"
                                    onClick={() => {
                                        void api(`/skills/${editing.id}`, {
                                            method: "DELETE",
                                        })
                                            .then(() => {
                                                refresh();
                                                setEditing(null);
                                            })
                                            .catch((e) => onError(e.message));
                                    }}
                                >
                                    <X size={14} />
                                    删除
                                </button>
                            ) : (
                                <span />
                            )}
                            {!editing.builtin && (
                                <button
                                    className="button primary"
                                    disabled={busy}
                                >
                                    保存 Skill
                                </button>
                            )}
                        </footer>
                    </form>
                </Modal>
            )}
        </section>
    );
}
