import { Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "./api";
import { Modal, Spinner } from "./ui";

export function DeleteButton({
    path,
    title,
    label = "删除",
    beforeDelete,
    onDeleted,
    onError,
}: {
    path: string;
    title: string;
    label?: string;
    beforeDelete?: () => Promise<void>;
    onDeleted: () => void | Promise<void>;
    onError: (message: string) => void;
}) {
    const [open, setOpen] = useState(false),
        [busy, setBusy] = useState(false);
    return (
        <>
            <button
                type="button"
                className="text-button delete-button"
                aria-label={label}
                onClick={() => setOpen(true)}
            >
                <Trash2 size={14} />
                {label}
            </button>
            {open && (
                <Modal
                    title="移到回收站"
                    onClose={() => {
                        if (!busy) setOpen(false);
                    }}
                >
                    <p>删除“{title}”？可在回收站恢复。</p>
                    <footer className="form-footer">
                        <button
                            type="button"
                            className="button secondary"
                            disabled={busy}
                            onClick={() => setOpen(false)}
                        >
                            取消
                        </button>
                        <button
                            type="button"
                            className="button primary"
                            disabled={busy}
                            onClick={async () => {
                                setBusy(true);
                                try {
                                    await beforeDelete?.();
                                    await api(path, { method: "DELETE" });
                                    setOpen(false);
                                    await onDeleted();
                                } catch (error) {
                                    onError((error as Error).message);
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            {busy && <Spinner />}确认删除
                        </button>
                    </footer>
                </Modal>
            )}
        </>
    );
}
