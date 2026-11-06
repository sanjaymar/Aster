import { Pencil } from "lucide-react";
import { useState } from "react";
import { api, send, type Conversation } from "../../shared/api";
import { DeleteButton } from "../../shared/DeleteButton";
import { Modal } from "../../shared/ui";

export function ConversationHistory({
    projectId,
    items,
    onSelect,
    onDeleted,
    onRefresh,
    onError,
}: {
    projectId: string;
    items: Conversation[];
    onSelect: (id: string) => void;
    onDeleted: (id: string) => void;
    onRefresh: () => void;
    onError: (message: string) => void;
}) {
    const [editing, setEditing] = useState<Conversation | null>(null),
        [busy, setBusy] = useState(false);
    return (
        <div className="conversation-list">
            {items.map((item) => (
                <div key={item.id} className="conversation-row">
                    <button onClick={() => onSelect(item.id)}>
                        {item.title}
                    </button>
                    <button
                        className="icon-button"
                        aria-label={`重命名对话 ${item.title}`}
                        onClick={() => setEditing(item)}
                    >
                        <Pencil size={13} />
                    </button>
                    <DeleteButton
                        path={`/projects/${projectId}/conversations/${item.id}`}
                        title={item.title}
                        label="删除对话"
                        onDeleted={() => {
                            onDeleted(item.id);
                            onRefresh();
                        }}
                        onError={onError}
                    />
                </div>
            ))}
            {items.length === 0 && <p className="plain-empty">暂无对话</p>}
            {editing && (
                <Modal title="重命名对话" onClose={() => setEditing(null)}>
                    <form
                        onSubmit={async (event) => {
                            event.preventDefault();
                            setBusy(true);
                            try {
                                await api(
                                    `/projects/${projectId}/conversations/${editing.id}`,
                                    send("PUT", { title: editing.title }),
                                );
                                setEditing(null);
                                onRefresh();
                            } catch (error) {
                                onError((error as Error).message);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        <input
                            aria-label="对话名称"
                            required
                            maxLength={200}
                            value={editing.title}
                            onChange={(e) =>
                                setEditing({
                                    ...editing,
                                    title: e.target.value,
                                })
                            }
                        />
                        <footer className="form-footer">
                            <span />
                            <button
                                className="button primary"
                                disabled={busy || !editing.title.trim()}
                            >
                                保存名称
                            </button>
                        </footer>
                    </form>
                </Modal>
            )}
        </div>
    );
}
