import { useState } from "react";
import { api, send, type Source } from "../../shared/api";
import { DeleteButton } from "../../shared/DeleteButton";
import { Field, Modal, Spinner } from "../../shared/ui";

export function SourceDetails({
    projectId,
    source,
    onClose,
    onSaved,
    onError,
}: {
    projectId: string;
    source: Source;
    onClose: () => void;
    onSaved: () => void;
    onError: (message: string) => void;
}) {
    const [values, setValues] = useState({
            title: source.title,
            authors: source.authors,
            year: source.year,
            doi: source.doi,
        }),
        [busy, setBusy] = useState(false);
    return (
        <Modal title="编辑资料" onClose={onClose}>
            <form
                onSubmit={async (event) => {
                    event.preventDefault();
                    setBusy(true);
                    try {
                        await api(
                            `/projects/${projectId}/sources/${source.id}`,
                            send("PUT", values),
                        );
                        onSaved();
                        onClose();
                    } catch (error) {
                        onError((error as Error).message);
                    } finally {
                        setBusy(false);
                    }
                }}
            >
                {(
                    [
                        ["title", "标题", 500],
                        ["authors", "作者", 10000],
                        ["year", "年份", 20],
                        ["doi", "DOI", 300],
                    ] as const
                ).map(([key, label, max]) => (
                    <Field label={label} key={key}>
                        <input
                            value={values[key]}
                            required={key === "title"}
                            maxLength={max}
                            onChange={(event) =>
                                setValues({
                                    ...values,
                                    [key]: event.target.value,
                                })
                            }
                        />
                    </Field>
                ))}
                <footer className="form-footer">
                    <DeleteButton
                        path={`/projects/${projectId}/sources/${source.id}`}
                        title={source.title}
                        label="删除资料"
                        onDeleted={() => {
                            onSaved();
                            onClose();
                        }}
                        onError={onError}
                    />
                    <button
                        className="button primary"
                        disabled={busy || !values.title.trim()}
                    >
                        {busy && <Spinner />}保存资料
                    </button>
                </footer>
            </form>
        </Modal>
    );
}
