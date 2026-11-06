import { RotateCcw, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api, send } from "../../shared/api";
import { Modal, Spinner, date } from "../../shared/ui";

type Item = { id: string; kind: string; title: string; deleted_at: string };
const labels: Record<string, string> = {
    project: "项目",
    source: "论文 / 资料",
    artifact: "文档",
    experiment: "方案与结果",
    conversation: "对话",
};
export function TrashDialog({
    projectId,
    onClose,
    onRefresh,
    onError,
}: {
    projectId: string;
    onClose: () => void;
    onRefresh: () => Promise<void>;
    onError: (message: string) => void;
}) {
    const [items, setItems] = useState<Item[] | null>(null),
        [query, setQuery] = useState(""),
        [busy, setBusy] = useState("");
    const load = () =>
        api<Item[]>(`/trash${projectId ? `?project_id=${projectId}` : ""}`)
            .then(setItems)
            .catch((error) => onError(error.message));
    useEffect(() => {
        void load();
    }, [projectId]);
    return (
        <Modal title="回收站" onClose={onClose} wide>
            <label className="search-box">
                <Search size={15} />
                <input
                    aria-label="搜索回收站"
                    placeholder="搜索"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                />
            </label>
            {!items ? (
                <Spinner />
            ) : (
                items
                    .filter((item) =>
                        item.title.toLowerCase().includes(query.toLowerCase()),
                    )
                    .map((item) => (
                        <div className="trash-row" key={item.id}>
                            <div>
                                <strong>{item.title}</strong>
                                <small>
                                    {labels[item.kind] || item.kind} ·{" "}
                                    {date(item.deleted_at)}
                                </small>
                            </div>
                            <button
                                className="text-button"
                                disabled={!!busy}
                                onClick={async () => {
                                    setBusy(item.id);
                                    try {
                                        await api(
                                            `/trash/${item.id}/restore`,
                                            send("POST", {}),
                                        );
                                        await load();
                                        await onRefresh();
                                    } catch (error) {
                                        onError((error as Error).message);
                                    } finally {
                                        setBusy("");
                                    }
                                }}
                            >
                                {busy === item.id ? (
                                    <Spinner />
                                ) : (
                                    <RotateCcw size={14} />
                                )}
                                恢复
                            </button>
                        </div>
                    ))
            )}
            {items?.length === 0 && <p className="plain-empty">回收站为空</p>}
        </Modal>
    );
}
