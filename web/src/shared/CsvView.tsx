import { useEffect, useState } from "react";
import { api, type Asset } from "./api";
import { Modal, Spinner } from "./ui";
export function CsvView({
    projectId,
    asset,
    onClose,
    onError,
}: {
    projectId: string;
    asset: Asset;
    onClose: () => void;
    onError: (s: string) => void;
}) {
    const [data, setData] = useState<{
        columns: string[];
        rows: Record<string, string>[];
        analyzed_rows: number;
        limit: number;
        numeric: Record<
            string,
            { count: number; min: number; max: number; mean: number }
        >;
    } | null>(null);
    useEffect(() => {
        api<typeof data>(`/projects/${projectId}/assets/${asset.id}/csv`)
            .then(setData)
            .catch((e) => onError(e.message));
    }, []);
    return (
        <Modal title={asset.name} onClose={onClose} wide>
            {data ? (
                <>
                    <p className="muted small">
                        描述性汇总基于前 {data.analyzed_rows} 行（最多{" "}
                        {data.limit} 行），表格展示前 100
                        行；有效数值计数不代表独立样本量。
                    </p>
                    <div className="csv-stats">
                        {Object.entries(data.numeric).map(([name, stats]) => (
                            <div key={name}>
                                <strong>{name}</strong>
                                <span>
                                    有效数值 {stats.count} · 均值{" "}
                                    {stats.mean.toPrecision(5)}
                                </span>
                                <small>
                                    最小 {stats.min} / 最大 {stats.max}
                                </small>
                            </div>
                        ))}
                    </div>
                    <div className="table-scroll">
                        <table>
                            <thead>
                                <tr>
                                    {data.columns.map((c) => (
                                        <th key={c}>{c}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {data.rows.map((r, i) => (
                                    <tr key={i}>
                                        {data.columns.map((c) => (
                                            <td key={c}>{r[c]}</td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            ) : (
                <Spinner />
            )}
        </Modal>
    );
}
