import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import {
    api,
    send,
    type Asset,
    type Experiment,
    type Version,
    type ExperimentResult,
} from "../../shared/api";
import { AttachmentPicker } from "../../shared/Attachments";
import { Field, Modal, Spinner, date } from "../../shared/ui";
import { RichTextEditor } from "../documents/RichTextEditor";
import { DeleteButton } from "../../shared/DeleteButton";
const planFields = [
    ["question", "研究问题"],
    ["hypothesis", "假设"],
    ["variables", "变量"],
    ["controls", "对照"],
    ["protocol", "步骤"],
    ["metrics", "指标"],
] as const;
export function ExperimentForm({
    projectId,
    experiment,
    onClose,
    onSaved,
    onError,
}: {
    projectId: string;
    experiment: Experiment | null;
    onClose: () => void;
    onSaved: () => void;
    onError: (message: string) => void;
}) {
    const [title, setTitle] = useState(experiment?.title || ""),
        [content, setContent] = useState(
            experiment?.plan.version.content || "",
        ),
        [fields, setFields] = useState<Record<string, unknown>>(
            experiment?.plan.version.fields || {},
        ),
        [assets, setAssets] = useState<Asset[]>(
            experiment?.plan.attachments || [],
        ),
        [busy, setBusy] = useState(false);
    return (
        <Modal
            title={experiment ? "编辑方案" : "新建方案"}
            onClose={onClose}
            wide
        >
            <form
                onSubmit={async (event) => {
                    event.preventDefault();
                    setBusy(true);
                    try {
                        await api(
                            `/projects/${projectId}/experiments${experiment ? `/${experiment.id}` : ""}`,
                            send(experiment ? "PUT" : "POST", {
                                title,
                                content:
                                    content ||
                                    planFields
                                        .map(
                                            ([key, label]) =>
                                                `## ${label}\n\n${fields[key] || ""}`,
                                        )
                                        .join("\n\n"),
                                fields,
                                expected_revision: experiment?.plan.revision,
                                asset_ids: assets.map((asset) => asset.id),
                            }),
                        );
                        onSaved();
                    } catch (error) {
                        onError((error as Error).message);
                    } finally {
                        setBusy(false);
                    }
                }}
            >
                <Field label="方案名称">
                    <input
                        required
                        aria-label="方案名称"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        maxLength={300}
                    />
                </Field>
                <RichTextEditor
                    label="实验方案正文"
                    value={content}
                    onChange={setContent}
                />
                <details className="plan-details">
                    <summary>结构化字段</summary>
                    <div className="form-columns">
                        {planFields.map(([key, label]) => (
                            <Field label={label} key={key}>
                                <textarea
                                    value={String(fields[key] || "")}
                                    onChange={(e) =>
                                        setFields({
                                            ...fields,
                                            [key]: e.target.value,
                                        })
                                    }
                                />
                            </Field>
                        ))}
                    </div>
                </details>
                <AttachmentPicker
                    projectId={projectId}
                    items={assets}
                    onChange={setAssets}
                    onError={onError}
                />
                <footer className="form-footer">
                    <span className="muted small">
                        {experiment
                            ? `方案 v${experiment.plan.revision}`
                            : "新方案"}
                    </span>
                    {experiment && (
                        <DeleteButton
                            path={`/projects/${projectId}/experiments/${experiment.id}`}
                            title={experiment.title}
                            label="删除方案及结果"
                            onDeleted={onSaved}
                            onError={onError}
                        />
                    )}
                    <button
                        className="button primary"
                        disabled={!title.trim() || busy}
                    >
                        {busy ? <Spinner /> : <Check size={15} />}保存方案
                    </button>
                </footer>
            </form>
        </Modal>
    );
}

export function ResultForm({
    projectId,
    experiment,
    result,
    onClose,
    onSaved,
    onError,
}: {
    projectId: string;
    experiment: Experiment;
    result?: ExperimentResult;
    onClose: () => void;
    onSaved: () => void;
    onError: (message: string) => void;
}) {
    const [versions, setVersions] = useState<Version[]>([]),
        [plan, setPlan] = useState(
            result?.plan_version_id || experiment.plan.version.id,
        ),
        [title, setTitle] = useState(
            result?.result.title || `${experiment.title} · 结果`,
        ),
        [conditions, setConditions] = useState(result?.conditions || ""),
        [content, setContent] = useState(result?.result.version.content || ""),
        [assets, setAssets] = useState<Asset[]>(
            result?.result.attachments || [],
        ),
        [busy, setBusy] = useState(false);
    useEffect(() => {
        void api<{ versions: Version[] }>(
            `/projects/${projectId}/artifacts/${experiment.plan.id}/history`,
        )
            .then((data) => setVersions(data.versions))
            .catch((error) => onError(error.message));
    }, [projectId, experiment.plan.id]);
    return (
        <Modal
            title={result ? "编辑实验结果" : "记录实验结果"}
            onClose={onClose}
            wide
        >
            <form
                onSubmit={async (event) => {
                    event.preventDefault();
                    setBusy(true);
                    try {
                        await api(
                            `/projects/${projectId}/experiments/${experiment.id}/results${result ? `/${result.id}` : ""}`,
                            send(result ? "PUT" : "POST", {
                                ...(result
                                    ? {
                                          expected_revision:
                                              result.result.revision,
                                      }
                                    : {}),
                                plan_version_id: plan,
                                title,
                                conditions,
                                content,
                                asset_ids: assets.map((asset) => asset.id),
                                fields: {
                                    ...(result?.result.version.fields || {}),
                                    schema_version: 1,
                                },
                            }),
                        );
                        onSaved();
                    } catch (error) {
                        onError((error as Error).message);
                    } finally {
                        setBusy(false);
                    }
                }}
            >
                <div className="form-columns">
                    <Field label="记录名称">
                        <input
                            required
                            value={title}
                            onChange={(e) => setTitle(e.target.value)}
                            maxLength={300}
                        />
                    </Field>
                    <Field label="采用的方案">
                        <select
                            value={plan}
                            onChange={(e) => setPlan(e.target.value)}
                        >
                            {versions.length ? (
                                versions.map((version) => (
                                    <option key={version.id} value={version.id}>
                                        v{version.number} ·{" "}
                                        {date(version.created_at)}
                                    </option>
                                ))
                            ) : (
                                <option value={experiment.plan.version.id}>
                                    v{experiment.plan.revision}
                                </option>
                            )}
                        </select>
                    </Field>
                </div>
                <Field label="实际条件与偏离">
                    <textarea
                        value={conditions}
                        onChange={(e) => setConditions(e.target.value)}
                    />
                </Field>
                <RichTextEditor
                    label="实验结果正文"
                    value={content}
                    onChange={setContent}
                />
                <AttachmentPicker
                    projectId={projectId}
                    items={assets}
                    onChange={setAssets}
                    onError={onError}
                />
                <footer className="form-footer">
                    {result ? (
                        <DeleteButton
                            path={`/projects/${projectId}/artifacts/${result.result.id}`}
                            title={result.result.title}
                            label="删除结果"
                            onDeleted={onSaved}
                            onError={onError}
                        />
                    ) : (
                        <span />
                    )}
                    <button
                        className="button primary"
                        disabled={!title.trim() || !content.trim() || busy}
                    >
                        {busy ? <Spinner /> : <Check size={15} />}保存结果
                    </button>
                </footer>
            </form>
        </Modal>
    );
}
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
