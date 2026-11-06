import { X } from "lucide-react";
import type { Source, RecordItem } from "../../shared/api";
import { noteTypes } from "./templates";

export type NoteProperties = {
    noteType: string;
    tags: string;
    pinned: boolean;
    sourceId: string;
    relatedIds: string[];
};
export function DocumentProperties({
    value,
    onChange,
    sources,
    records,
    id,
    onReference,
}: {
    value: NoteProperties;
    onChange: (v: NoteProperties) => void;
    sources: Source[];
    records: RecordItem[];
    id?: string;
    onReference: (r: RecordItem) => void;
}) {
    const backlinks = id
        ? records.filter(
              (r) =>
                  Array.isArray(r.version.fields.related_record_ids) &&
                  r.version.fields.related_record_ids.includes(id),
          )
        : [];
    return (
        <aside className="document-properties" aria-label="文档属性">
            <h3>属性</h3>
            <label className="field">
                <span>类型</span>
                <select
                    aria-label="文档类型"
                    value={value.noteType}
                    onChange={(e) =>
                        onChange({ ...value, noteType: e.target.value })
                    }
                >
                    {Object.entries(noteTypes).map(([key, label]) => (
                        <option key={key} value={key}>
                            {label}
                        </option>
                    ))}
                </select>
            </label>
            <label className="field">
                <span>标签</span>
                <input
                    aria-label="文档标签"
                    value={value.tags}
                    placeholder="逗号分隔"
                    maxLength={380}
                    onChange={(e) =>
                        onChange({ ...value, tags: e.target.value })
                    }
                />
            </label>
            <label className="check-label">
                <input
                    type="checkbox"
                    checked={value.pinned}
                    onChange={(e) =>
                        onChange({ ...value, pinned: e.target.checked })
                    }
                />
                置顶
            </label>
            <label className="field">
                <span>关联文献</span>
                <select
                    aria-label="关联文献"
                    value={value.sourceId}
                    onChange={(e) =>
                        onChange({ ...value, sourceId: e.target.value })
                    }
                >
                    <option value="">无</option>
                    {sources.map((s) => (
                        <option value={s.id} key={s.id}>
                            {s.title}
                        </option>
                    ))}
                </select>
            </label>
            <label className="field">
                <span>关联文档</span>
                <select
                    aria-label="添加关联文档"
                    value=""
                    onChange={(e) => {
                        if (e.target.value)
                            onChange({
                                ...value,
                                relatedIds: [
                                    ...value.relatedIds,
                                    e.target.value,
                                ],
                            });
                    }}
                >
                    <option value="">选择文档…</option>
                    {records
                        .filter(
                            (r) =>
                                r.id !== id && !value.relatedIds.includes(r.id),
                        )
                        .map((r) => (
                            <option key={r.id} value={r.id}>
                                {r.title}
                            </option>
                        ))}
                </select>
            </label>
            {value.relatedIds.map((key) => {
                const r = records.find((r) => r.id === key);
                return (
                    <div className="related-document" key={key}>
                        <span>{r?.title || "已归档文档"}</span>
                        {r && (
                            <button
                                className="text-button"
                                onClick={() => onReference(r)}
                            >
                                引用
                            </button>
                        )}
                        <button
                            className="icon-button"
                            aria-label="移除关联"
                            onClick={() =>
                                onChange({
                                    ...value,
                                    relatedIds: value.relatedIds.filter(
                                        (i) => i !== key,
                                    ),
                                })
                            }
                        >
                            <X size={12} />
                        </button>
                    </div>
                );
            })}
            {!!backlinks.length && (
                <>
                    <h3>被这些文档关联</h3>
                    {backlinks.map((r) => (
                        <p className="muted small" key={r.id}>
                            {r.title}
                        </p>
                    ))}
                </>
            )}
        </aside>
    );
}
