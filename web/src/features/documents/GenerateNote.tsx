import { useState } from "react";
import { WandSparkles, BookOpen, ListChecks, Columns3 } from "lucide-react";
import { Modal, Spinner } from "../../shared/ui";
import type { Source } from "../../shared/api";
import {
    AssistantOptions,
    useAssistantOptions,
} from "../assistant/AssistantOptions";
import { Materials } from "../slides/Materials";
import type { ResearchTask } from "../workspace/Home";
const methods = [
    {
        id: "paper-reading",
        name: "论文精读",
        text: "问题、方法、发现、局限与原文图版",
        icon: BookOpen,
    },
    {
        id: "method-card",
        name: "方法笔记",
        text: "输入、关键步骤、参数与适用边界",
        icon: ListChecks,
    },
    {
        id: "literature-review",
        name: "文献对照",
        text: "并列比较研究设计、证据与结论",
        icon: Columns3,
    },
];
export function GenerateNote({
    sources,
    onStart,
    onClose,
    onError,
}: {
    sources: Source[];
    onStart: (task: ResearchTask) => Promise<void>;
    onClose: () => void;
    onError: (m: string) => void;
}) {
    const [selected, setSelected] = useState<string[]>([]),
        [method, setMethod] = useState("paper-reading"),
        [request, setRequest] = useState(""),
        [busy, setBusy] = useState(false);
    const options = useAssistantOptions(true);
    return (
        <Modal title="生成阅读笔记" onClose={onClose} wide>
            <div className="note-generation">
                <div className="note-methods">
                    {methods.map((m) => (
                        <button
                            className={method === m.id ? "active" : ""}
                            key={m.id}
                            onClick={() => {
                                setMethod(m.id);
                                setSelected((ids) =>
                                    ids.slice(
                                        0,
                                        m.id === "literature-review" ? 6 : 1,
                                    ),
                                );
                            }}
                        >
                            <m.icon size={18} />
                            <strong>{m.name}</strong>
                            <small>{m.text}</small>
                        </button>
                    ))}
                </div>
                <Materials
                    label="论文"
                    items={sources}
                    selected={selected}
                    limit={method === "literature-review" ? 6 : 1}
                    onChange={setSelected}
                />
                <label>
                    关注的问题
                    <textarea
                        value={request}
                        onChange={(e) => setRequest(e.target.value)}
                        placeholder="例如：重点解释样本设计、质控过程和结果是否支持结论"
                        maxLength={3000}
                    />
                </label>
                <AssistantOptions options={options} reader disabled={busy} />
                <div className="note-generation-footer">
                    <span>
                        生成后保存为可编辑笔记，原文引用与配图一并保留。
                    </span>
                    <button
                        className="button primary"
                        disabled={
                            busy ||
                            !selected.length ||
                            (method === "literature-review" &&
                                selected.length < 2)
                        }
                        onClick={async () => {
                            setBusy(true);
                            try {
                                await onStart({
                                    prompt:
                                        request ||
                                        "请生成结构完整、内容具体的论文精读报告，覆盖背景、方法与数据、主要发现、局限及待追问问题。",
                                    mode: "reading",
                                    scope: "selected",
                                    responseStyle: "grounded",
                                    sourceIds: selected,
                                    skillId: options.skillId || method,
                                    modelId: options.modelId,
                                });
                                onClose();
                            } catch (e) {
                                onError((e as Error).message);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        {busy ? <Spinner /> : <WandSparkles size={14} />}
                        生成笔记
                    </button>
                </div>
            </div>
        </Modal>
    );
}
