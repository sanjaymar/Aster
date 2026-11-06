import {
    ArrowUpRight,
    Check,
    FlaskConical,
    Plus,
    Search,
    Pencil,
} from "lucide-react";
import {
    type Asset,
    type Bundle,
    type Experiment,
    type RecordItem,
    type ExperimentResult,
} from "../../shared/api";
import { AssetList, Empty, date } from "../../shared/components";

import { useState, type Dispatch, type SetStateAction } from "react";
import { RecordCollection } from "../documents/RecordCollection";

export function ExperimentsPage({
    bundle,
    artifactIds,
    setArtifactIds,
    setExperimentModal,
    setResultModal,
    setCsv,
    openRecord,
    onNewLog,
}: {
    bundle: Bundle;
    artifactIds: string[];
    setArtifactIds: Dispatch<SetStateAction<string[]>>;
    setExperimentModal: (v: Experiment | null | undefined) => void;
    setResultModal: (v: Experiment | null, result?: ExperimentResult) => void;
    setCsv: (v: Asset | null) => void;
    openRecord: (r: RecordItem) => void;
    onNewLog: () => void;
}) {
    const [tab, setTab] = useState("logs");
    const [query, setQuery] = useState("");
    const matching = (text: string) =>
        text.toLowerCase().includes(query.toLowerCase());
    return (
        <>
            <div className="page-heading">
                <div>
                    <span className="eyebrow">实验</span>
                    <h1>实验记录</h1>
                </div>
                <button
                    className="button primary"
                    onClick={() =>
                        tab === "logs" ? onNewLog() : setExperimentModal(null)
                    }
                >
                    <Plus size={16} />
                    {tab === "logs" ? "新建实验记录" : "新建方案"}
                </button>
            </div>
            <div className="segmented experiment-tabs">
                <button
                    className={tab === "logs" ? "active" : ""}
                    onClick={() => setTab("logs")}
                >
                    实验日志
                </button>
                <button
                    className={tab === "plans" ? "active" : ""}
                    onClick={() => setTab("plans")}
                >
                    方案与结果
                </button>
            </div>
            <label className="search-box experiment-search">
                <Search size={15} />
                <input
                    aria-label="搜索实验记录"
                    placeholder="搜索标题或正文"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                />
            </label>
            {tab === "logs" ? (
                <RecordCollection
                    items={bundle.records.filter(
                        (record) =>
                            record.kind === "labnote" &&
                            matching(
                                record.title + " " + record.version.content,
                            ),
                    )}
                    selected={artifactIds}
                    onToggle={(id) =>
                        setArtifactIds((ids) =>
                            ids.includes(id)
                                ? ids.filter((item) => item !== id)
                                : [...ids, id],
                        )
                    }
                    onOpen={openRecord}
                    kind="labnote"
                    onNew={onNewLog}
                />
            ) : bundle.experiments.length ? (
                <div className="experiment-list">
                    {bundle.experiments
                        .filter((exp) =>
                            matching(
                                exp.title +
                                    " " +
                                    exp.plan.version.content +
                                    " " +
                                    exp.runs
                                        .map(
                                            (run) => run.result.version.content,
                                        )
                                        .join(" "),
                            ),
                        )
                        .map((exp) => (
                            <article className="experiment-card" key={exp.id}>
                                <div className="section-heading">
                                    <div>
                                        <span className="eyebrow">
                                            实验方案 v{exp.plan.revision}
                                        </span>
                                        <h2>{exp.title}</h2>
                                    </div>
                                    <button
                                        className="text-button"
                                        onClick={() => setExperimentModal(exp)}
                                    >
                                        编辑方案
                                        <ArrowUpRight size={14} />
                                    </button>
                                </div>
                                <p className="experiment-summary">
                                    {String(
                                        exp.plan.version.fields.hypothesis ||
                                            exp.plan.version.content.slice(
                                                0,
                                                160,
                                            ) ||
                                            "还没有填写假设",
                                    )}
                                </p>
                                <div className="inline plan-actions">
                                    <button
                                        className="button secondary"
                                        onClick={() => setResultModal(exp)}
                                    >
                                        <Plus size={14} />
                                        记录结果
                                    </button>
                                    <button
                                        className={
                                            "chip " +
                                            (artifactIds.includes(exp.plan.id)
                                                ? "active"
                                                : "")
                                        }
                                        onClick={() =>
                                            setArtifactIds((ids) =>
                                                ids.includes(exp.plan.id)
                                                    ? ids.filter(
                                                          (id) =>
                                                              id !==
                                                              exp.plan.id,
                                                      )
                                                    : [...ids, exp.plan.id],
                                            )
                                        }
                                    >
                                        {artifactIds.includes(exp.plan.id) ? (
                                            <Check size={13} />
                                        ) : (
                                            <Plus size={13} />
                                        )}
                                        加入助手材料
                                    </button>
                                    <span className="muted small">
                                        {exp.runs.length} 次执行记录
                                    </span>
                                </div>
                                {exp.runs.map((r) => (
                                    <div key={r.id} className="experiment-run">
                                        <div className="run-mark" />
                                        <div>
                                            <button
                                                className="text-button"
                                                onClick={() =>
                                                    openRecord(r.result)
                                                }
                                            >
                                                {r.result.title}
                                                <ArrowUpRight size={14} />
                                            </button>
                                            <p className="muted small">
                                                采用方案 v{r.plan_version} ·{" "}
                                                {date(r.created_at)}
                                                {r.conditions
                                                    ? " · " + r.conditions
                                                    : ""}
                                            </p>
                                            <AssetList
                                                items={r.result.attachments}
                                                onCsv={setCsv}
                                            />
                                        </div>
                                        <button
                                            className={
                                                "icon-button " +
                                                (artifactIds.includes(
                                                    r.result.id,
                                                )
                                                    ? "selected"
                                                    : "")
                                            }
                                            onClick={() =>
                                                setArtifactIds((ids) =>
                                                    ids.includes(r.result.id)
                                                        ? ids.filter(
                                                              (id) =>
                                                                  id !==
                                                                  r.result.id,
                                                          )
                                                        : [...ids, r.result.id],
                                                )
                                            }
                                            aria-label={
                                                "选择结果 " + r.result.title
                                            }
                                        >
                                            {artifactIds.includes(
                                                r.result.id,
                                            ) ? (
                                                <Check size={16} />
                                            ) : (
                                                <Plus size={16} />
                                            )}
                                        </button>
                                        <button
                                            className="text-button"
                                            aria-label={`编辑结果 ${r.result.title}`}
                                            onClick={() =>
                                                setResultModal(exp, r)
                                            }
                                        >
                                            <Pencil size={13} />
                                            编辑结果
                                        </button>
                                    </div>
                                ))}
                            </article>
                        ))}
                </div>
            ) : (
                <Empty
                    icon={<FlaskConical size={30} />}
                    title="暂无实验"
                    action={
                        <button
                            className="button secondary"
                            onClick={() => setExperimentModal(null)}
                        >
                            记录第一份实验方案
                        </button>
                    }
                ></Empty>
            )}
        </>
    );
}
