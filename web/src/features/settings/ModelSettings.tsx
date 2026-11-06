import { Check, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
    api,
    send,
    type ModelState,
    type ModelProfile,
    type ProfileState,
} from "../../shared/api";
import { Field, Spinner } from "../../shared/components";
import { SkillSettings } from "./SkillSettings";

const fresh: ModelProfile = {
    id: "",
    name: "",
    provider: "compatible",
    base_url: "http://127.0.0.1:8000/v1",
    model: "auto",
    max_tokens: 4096,
    timeout: 600,
    key_env: "",
};

export function ModelSettings({
    onUpdate,
    onError,
    notify,
}: {
    model: ModelState | null;
    onUpdate: (m: ModelState) => void;
    onError: (s: string) => void;
    notify: (s: string) => void;
}) {
    const [tab, setTab] = useState("models"),
        [state, setState] = useState<ProfileState | null>(null);
    const [draft, setDraft] = useState<ModelProfile>(fresh),
        [key, setKey] = useState(""),
        [clear, setClear] = useState(false);
    const [busy, setBusy] = useState(false),
        [status, setStatus] = useState("");
    useEffect(() => {
        void api<ProfileState>("/models/profiles")
            .then((s) => {
                setState(s);
                setDraft(s.profiles[0]);
            })
            .catch((e) => onError(e.message));
    }, []);
    function choose(p: ModelProfile) {
        setDraft({ ...p });
        setKey("");
        setClear(false);
        setStatus("");
    }
    async function update(next: ProfileState) {
        setState(next);
        window.dispatchEvent(new Event("aster:models-updated"));
        onUpdate(await api<ModelState>("/model"));
    }
    async function save(e: React.FormEvent) {
        e.preventDefault();
        setBusy(true);
        try {
            const { id, has_key: _hasKey, ...body } = draft;
            const next = await api<ProfileState>(
                `/models/profiles${id ? "/" + id : ""}`,
                send(id ? "PUT" : "POST", {
                    ...body,
                    ...(key ? { api_key: key } : {}),
                    clear_key: clear,
                }),
            );
            await update(next);
            choose(
                id
                    ? next.profiles.find((p) => p.id === id)!
                    : next.profiles.at(-1)!,
            );
            notify("模型配置已保存");
        } catch (e) {
            onError((e as Error).message);
        } finally {
            setBusy(false);
        }
    }
    return (
        <>
            <div className="page-heading">
                <h1>设置</h1>
            </div>
            <div className="settings-tabs" role="tablist" aria-label="设置分类">
                <button
                    role="tab"
                    aria-selected={tab === "models"}
                    onClick={() => setTab("models")}
                >
                    模型
                </button>
                <button
                    role="tab"
                    aria-selected={tab === "skills"}
                    onClick={() => setTab("skills")}
                >
                    Skills
                </button>
            </div>
            {tab === "skills" ? (
                <SkillSettings onError={onError} notify={notify} />
            ) : (
                state && (
                    <>
                        <section className="settings-panel model-defaults">
                            {(
                                [
                                    ["assistant", "科研问答"],
                                    ["reader", "PDF 问答"],
                                ] as const
                            ).map(([purpose, label]) => (
                                <Field label={label + "默认模型"} key={purpose}>
                                    <select
                                        aria-label={label + "默认模型"}
                                        value={state.defaults[purpose]}
                                        onChange={(e) => {
                                            void api<ProfileState>(
                                                "/models/defaults",
                                                send("PUT", {
                                                    ...state.defaults,
                                                    [purpose]: e.target.value,
                                                }),
                                            )
                                                .then(update)
                                                .catch((e) =>
                                                    onError(e.message),
                                                );
                                        }}
                                    >
                                        {state.profiles.map((p) => (
                                            <option value={p.id} key={p.id}>
                                                {p.name}
                                            </option>
                                        ))}
                                    </select>
                                </Field>
                            ))}
                        </section>
                        <div className="model-settings-grid">
                            <aside className="model-profile-list">
                                {state.profiles.map((p) => (
                                    <button
                                        className={
                                            p.id === draft.id ? "active" : ""
                                        }
                                        key={p.id}
                                        onClick={() => choose(p)}
                                    >
                                        <strong>{p.name}</strong>
                                        <span>
                                            {p.provider === "codex"
                                                ? "Codex CLI"
                                                : p.model}
                                        </span>
                                    </button>
                                ))}
                                <button
                                    className="text-button"
                                    onClick={() => choose(fresh)}
                                >
                                    <Plus size={15} />
                                    添加模型
                                </button>
                            </aside>
                            <form
                                className="settings-panel model-profile-form"
                                onSubmit={save}
                            >
                                <div className="section-heading">
                                    <h2>{draft.id ? "编辑配置" : "新模型"}</h2>
                                    {draft.id && (
                                        <button
                                            type="button"
                                            className="text-button"
                                            disabled={busy}
                                            onClick={() => {
                                                setBusy(true);
                                                void api<ModelState>(
                                                    `/models/profiles/${draft.id}/health`,
                                                )
                                                    .then((s) =>
                                                        setStatus(
                                                            s.connected
                                                                ? `可用 · ${s.selected === "auto" ? "Codex 默认模型" : s.selected}`
                                                                : s.error ||
                                                                      "服务暂不可用",
                                                        ),
                                                    )
                                                    .catch((e) =>
                                                        onError(e.message),
                                                    )
                                                    .finally(() =>
                                                        setBusy(false),
                                                    );
                                            }}
                                        >
                                            <RefreshCw size={14} />
                                            检查连接
                                        </button>
                                    )}
                                </div>
                                <Field label="配置名称">
                                    <input
                                        required
                                        aria-label="配置名称"
                                        value={draft.name}
                                        maxLength={100}
                                        onChange={(e) =>
                                            setDraft({
                                                ...draft,
                                                name: e.target.value,
                                            })
                                        }
                                    />
                                </Field>
                                <Field label="接入方式">
                                    <select
                                        value={draft.provider}
                                        onChange={(e) =>
                                            setDraft({
                                                ...draft,
                                                provider: e.target
                                                    .value as ModelProfile["provider"],
                                                ...(e.target.value === "openai"
                                                    ? {
                                                          base_url:
                                                              "https://api.openai.com/v1",
                                                      }
                                                    : {}),
                                            })
                                        }
                                    >
                                        <option value="compatible">
                                            OpenAI 兼容 API · Qwen / Ollama /
                                            vLLM
                                        </option>
                                        <option value="openai">
                                            OpenAI API
                                        </option>
                                        <option value="codex">
                                            Codex CLI · 使用已有登录
                                        </option>
                                    </select>
                                </Field>
                                {draft.provider !== "codex" ? (
                                    <>
                                        <Field label="API 地址">
                                            <input
                                                type="url"
                                                required
                                                aria-label="API 地址"
                                                value={draft.base_url}
                                                onChange={(e) =>
                                                    setDraft({
                                                        ...draft,
                                                        base_url:
                                                            e.target.value,
                                                    })
                                                }
                                            />
                                        </Field>
                                        <Field label="API Key">
                                            <input
                                                type="password"
                                                autoComplete="new-password"
                                                aria-label="API Key"
                                                value={key}
                                                placeholder={
                                                    draft.has_key
                                                        ? "已保存，留空保留"
                                                        : "本地无鉴权服务可留空"
                                                }
                                                onChange={(e) =>
                                                    setKey(e.target.value)
                                                }
                                            />
                                        </Field>
                                        <details className="model-advanced">
                                            <summary>高级选项</summary>
                                            {draft.provider ===
                                                "compatible" && (
                                                <label className="check-label">
                                                    <input
                                                        type="checkbox"
                                                        checked={
                                                            !!draft.disable_thinking
                                                        }
                                                        onChange={(e) =>
                                                            setDraft({
                                                                ...draft,
                                                                disable_thinking:
                                                                    e.target
                                                                        .checked,
                                                            })
                                                        }
                                                    />
                                                    关闭 Qwen
                                                    思考输出（需服务支持）
                                                </label>
                                            )}
                                            <Field label="或使用服务端环境变量">
                                                <input
                                                    value={draft.key_env}
                                                    placeholder="MY_MODEL_API_KEY"
                                                    onChange={(e) =>
                                                        setDraft({
                                                            ...draft,
                                                            key_env:
                                                                e.target.value,
                                                        })
                                                    }
                                                />
                                            </Field>
                                            <label className="check-label">
                                                <input
                                                    type="checkbox"
                                                    checked={clear}
                                                    onChange={(e) =>
                                                        setClear(
                                                            e.target.checked,
                                                        )
                                                    }
                                                />
                                                清除已保存密钥
                                            </label>
                                        </details>
                                    </>
                                ) : (
                                    <p className="muted small">
                                        使用本机 Codex 登录；请先在终端运行{" "}
                                        <code>codex login</code>
                                        。资料会发送到该账户的模型服务。Aster
                                        只开放资料检索工具。
                                    </p>
                                )}
                                <Field label="模型名称">
                                    <input
                                        required
                                        aria-label="模型名称"
                                        value={draft.model}
                                        maxLength={200}
                                        placeholder={
                                            draft.provider === "codex"
                                                ? "auto 使用 Codex 默认模型"
                                                : draft.provider === "openai"
                                                  ? "填写API模型名称"
                                                  : "服务中的模型名称；auto 自动选择"
                                        }
                                        onChange={(e) =>
                                            setDraft({
                                                ...draft,
                                                model: e.target.value,
                                            })
                                        }
                                    />
                                </Field>
                                <div className="form-columns">
                                    <Field
                                        label={
                                            draft.provider === "codex"
                                                ? "输出长度参考（tokens）"
                                                : "最大输出 tokens"
                                        }
                                    >
                                        <input
                                            type="number"
                                            min={128}
                                            max={16384}
                                            value={draft.max_tokens}
                                            onChange={(e) =>
                                                setDraft({
                                                    ...draft,
                                                    max_tokens: Number(
                                                        e.target.value,
                                                    ),
                                                })
                                            }
                                        />
                                    </Field>
                                    <Field label="超时（秒）">
                                        <input
                                            type="number"
                                            min={15}
                                            max={900}
                                            value={draft.timeout}
                                            onChange={(e) =>
                                                setDraft({
                                                    ...draft,
                                                    timeout: Number(
                                                        e.target.value,
                                                    ),
                                                })
                                            }
                                        />
                                    </Field>
                                </div>
                                {status && (
                                    <p
                                        className="model-check-result"
                                        role="status"
                                    >
                                        {status}
                                    </p>
                                )}
                                <footer className="form-footer">
                                    {draft.id &&
                                    !Object.values(state.defaults).includes(
                                        draft.id,
                                    ) ? (
                                        <button
                                            type="button"
                                            className="text-button danger"
                                            disabled={busy}
                                            onClick={() => {
                                                void api<ProfileState>(
                                                    `/models/profiles/${draft.id}`,
                                                    { method: "DELETE" },
                                                )
                                                    .then(async (s) => {
                                                        await update(s);
                                                        choose(s.profiles[0]);
                                                    })
                                                    .catch((e) =>
                                                        onError(e.message),
                                                    );
                                            }}
                                        >
                                            <Trash2 size={14} />
                                            删除配置
                                        </button>
                                    ) : (
                                        <span />
                                    )}
                                    <button
                                        className="button primary"
                                        disabled={busy}
                                    >
                                        {busy ? (
                                            <Spinner />
                                        ) : (
                                            <Check size={15} />
                                        )}
                                        保存配置
                                    </button>
                                </footer>
                                <p className="muted small">
                                    密钥仅保存于后端，不随项目备份导出。
                                </p>
                            </form>
                        </div>
                    </>
                )
            )}
        </>
    );
}
