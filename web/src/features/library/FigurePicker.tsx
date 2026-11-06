import { useEffect, useState } from "react";
import { api } from "../../shared/api";
import { Modal, Spinner } from "../../shared/ui";
export type Figure = {
    asset_id: string;
    source_id: string;
    version_id: string;
    page: number;
    caption: string;
    label: string;
    citation: string;
    url: string;
    kind: string;
};
export function FigurePicker({
    projectId,
    sourceIds,
    onSelect,
    onClose,
}: {
    projectId: string;
    sourceIds: string[];
    onSelect: (f: Figure) => void;
    onClose: () => void;
}) {
    const [figures, setFigures] = useState<Figure[]>([]),
        [loading, setLoading] = useState(true),
        [error, setError] = useState("");
    useEffect(() => {
        let live = true;
        Promise.all(
            sourceIds.map((id) =>
                api<{ figures: Figure[] }>(
                    `/projects/${projectId}/sources/${id}/figures`,
                ),
            ),
        )
            .then((rows) => {
                if (live) setFigures(rows.flatMap((r) => r.figures));
            })
            .catch((e) => {
                if (live) setError(e.message);
            })
            .finally(() => {
                if (live) setLoading(false);
            });
        return () => {
            live = false;
        };
    }, [projectId, sourceIds.join(",")]);
    return (
        <Modal title="原文图版" onClose={onClose} wide>
            <div className="figure-library">
                {loading ? (
                    <Spinner />
                ) : error ? (
                    <p>{error}</p>
                ) : !figures.length ? (
                    <p>未提取到可用图版，可上传原文截图。</p>
                ) : (
                    figures.map((f) => (
                        <button
                            key={f.asset_id}
                            onClick={() => {
                                onSelect(f);
                                onClose();
                            }}
                        >
                            <img src={f.url} alt={f.label} />
                            <strong>{f.label}</strong>
                            <small>{f.caption}</small>
                        </button>
                    ))
                )}
            </div>
        </Modal>
    );
}
