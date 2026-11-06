import { useState } from "react";
import {
    ArrowLeft,
    ArrowDown,
    ArrowUp,
    Download,
    Plus,
    Save,
    Trash2,
    ImagePlus,
} from "lucide-react";
import { api, send, type Asset, type RecordItem } from "../../shared/api";
import { Spinner } from "../../shared/ui";
import { DeleteButton } from "../../shared/DeleteButton";
import type { Deck, Slide } from "./SlidesPage";
import { SlidePreview, layouts } from "./SlidePreview";
import { FigurePicker } from "../library/FigurePicker";
export function SlideEditor({
    projectId,
    record,
    onClose,
    onSaved,
    onError,
    onEvidence,
}: {
    projectId: string;
    record: RecordItem;
    onClose: () => void;
    onSaved: () => void;
    onError: (m: string) => void;
    onEvidence: (kind: string, id: string) => void;
}) {
    const [deck, setDeck] = useState<Deck>(() =>
            structuredClone(record.version.fields.deck as Deck),
        ),
        [revision, setRevision] = useState(record.revision),
        [active, setActive] = useState(0),
        [busy, setBusy] = useState(false),
        [dirty, setDirty] = useState(false);
    const slide = deck.slides[active];
    const [figuresOpen, setFiguresOpen] = useState(false);
    const update = (v: Deck) => {
        setDeck(v);
        setDirty(true);
    };
    const edit = (v: Partial<Slide>) =>
        update({
            ...deck,
            slides: deck.slides.map((s, i) =>
                i === active ? { ...s, ...v } : s,
            ),
        });
    async function save() {
        setBusy(true);
        try {
            const r = await api<RecordItem>(
                `/projects/${projectId}/decks/${record.id}`,
                send("PUT", { ...deck, expected_revision: revision }),
            );
            setRevision(r.revision);
            setDirty(false);
            onSaved();
        } catch (e) {
            onError((e as Error).message);
        } finally {
            setBusy(false);
        }
    }
    function move(step: number) {
        const next = active + step;
        if (next < 0 || next >= deck.slides.length) return;
        const slides = [...deck.slides];
        [slides[active], slides[next]] = [slides[next], slides[active]];
        update({ ...deck, slides });
        setActive(next);
    }
    return (
        <div className="deck-editor">
            <header className="deck-toolbar">
                <button
                    className="icon-button"
                    aria-label="关闭汇报"
                    onClick={() => {
                        if (!dirty || confirm("尚未保存的修改将丢失，关闭？"))
                            onClose();
                    }}
                >
                    <ArrowLeft size={18} />
                </button>
                <input
                    aria-label="汇报标题"
                    value={deck.title}
                    onChange={(e) => update({ ...deck, title: e.target.value })}
                    maxLength={200}
                />
                <select
                    aria-label="汇报主题"
                    value={deck.theme}
                    onChange={(e) =>
                        update({
                            ...deck,
                            theme: e.target.value as Deck["theme"],
                        })
                    }
                >
                    <option value="academic">Academic · 学术蓝</option>
                    <option value="paper">Paper · 浅色</option>
                    <option value="ink">Ink · 深色</option>
                </select>
                <button
                    className="button primary"
                    onClick={save}
                    disabled={busy || !dirty}
                >
                    {busy ? <Spinner /> : <Save size={14} />}保存
                </button>
                <a
                    className={`button secondary ${dirty ? "disabled-link" : ""}`}
                    aria-disabled={dirty}
                    href={`/api/projects/${projectId}/decks/${record.id}/export`}
                    onClick={(e) => {
                        if (dirty) {
                            e.preventDefault();
                            onError("请先保存修改");
                        }
                    }}
                >
                    <Download size={14} />
                    PPTX
                </a>
                <DeleteButton
                    label="删除汇报"
                    title={record.title}
                    path={`/projects/${projectId}/artifacts/${record.id}`}
                    onDeleted={() => {
                        onSaved();
                        onClose();
                    }}
                    onError={onError}
                />
            </header>
            <div className="deck-workspace">
                <nav className="deck-outline" aria-label="幻灯片列表">
                    {deck.slides.map((s, i) => (
                        <button
                            key={i}
                            className={i === active ? "active" : ""}
                            onClick={() => setActive(i)}
                        >
                            <div className="slide-thumb">
                                <SlidePreview
                                    slide={s}
                                    deck={deck}
                                    page={i + 1}
                                    projectId={projectId}
                                />
                            </div>
                            <span>
                                {String(i + 1).padStart(2, "0")} · {s.title}
                            </span>
                        </button>
                    ))}
                    <button
                        onClick={() => {
                            update({
                                ...deck,
                                slides: [
                                    ...deck.slides,
                                    {
                                        title: "新的一页",
                                        bullets: [],
                                        notes: "",
                                        citations: [],
                                    },
                                ],
                            });
                            setActive(deck.slides.length);
                        }}
                        disabled={deck.slides.length >= 30}
                    >
                        <Plus size={14} />
                        添加一页
                    </button>
                </nav>
                <main className="deck-main">
                    <SlidePreview
                        slide={slide}
                        deck={deck}
                        page={active + 1}
                        projectId={projectId}
                    />
                    <label>
                        讲者备注
                        <textarea
                            value={slide.notes}
                            onChange={(e) => edit({ notes: e.target.value })}
                            maxLength={3000}
                        />
                    </label>
                    <details className="deck-skill-export">
                        <summary>用 Codex PPT 制作整页视觉稿</summary>
                        <p>
                            下载提纲与引用包，在已安装 codex-ppt skill 的 Codex
                            中打开。需要可用的生图模型；先确认单页样稿。
                        </p>
                        <a
                            href={`/api/projects/${projectId}/decks/${record.id}/pack`}
                            className="button secondary"
                            onClick={(e) => {
                                if (dirty) {
                                    e.preventDefault();
                                    onError("请先保存修改");
                                }
                            }}
                        >
                            下载材料包
                        </a>{" "}
                        <a
                            href="https://github.com/ningzimu/codex-ppt-skill"
                            target="_blank"
                            rel="noreferrer"
                        >
                            Skill ↗
                        </a>
                    </details>
                </main>
                <aside className="slide-properties">
                    <div className="inline spread">
                        <strong>第 {active + 1} 页</strong>
                        <div className="inline">
                            <button
                                className="icon-button"
                                aria-label="上一位"
                                disabled={active === 0}
                                onClick={() => move(-1)}
                            >
                                <ArrowUp size={14} />
                            </button>
                            <button
                                className="icon-button"
                                aria-label="下一位"
                                disabled={active === deck.slides.length - 1}
                                onClick={() => move(1)}
                            >
                                <ArrowDown size={14} />
                            </button>
                            <button
                                className="icon-button"
                                aria-label="删除此页"
                                disabled={deck.slides.length === 1}
                                onClick={() => {
                                    update({
                                        ...deck,
                                        slides: deck.slides.filter(
                                            (_, i) => i !== active,
                                        ),
                                    });
                                    setActive(Math.max(0, active - 1));
                                }}
                            >
                                <Trash2 size={14} />
                            </button>
                        </div>
                    </div>
                    <label>
                        版式
                        <select
                            aria-label="幻灯片版式"
                            value={slide.layout || "bullets"}
                            onChange={(e) =>
                                edit({
                                    layout: e.target.value as Slide["layout"],
                                })
                            }
                        >
                            {Object.entries(layouts).map(([key, label]) => (
                                <option key={key} value={key}>
                                    {label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label>
                        副标题
                        <input
                            value={slide.subtitle || ""}
                            maxLength={180}
                            onChange={(e) => edit({ subtitle: e.target.value })}
                        />
                    </label>
                    <label>
                        标题
                        <input
                            value={slide.title}
                            maxLength={100}
                            onChange={(e) => edit({ title: e.target.value })}
                        />
                    </label>
                    {slide.layout === "flow" && (
                        <label>
                            流程 · 每行“步骤 | 说明”
                            <textarea
                                aria-label="方法流程"
                                value={(slide.steps || [])
                                    .map(
                                        (s) =>
                                            s.label +
                                            (s.detail ? " | " + s.detail : ""),
                                    )
                                    .join("\n")}
                                onChange={(e) =>
                                    edit({
                                        steps: e.target.value
                                            .split("\n")
                                            .slice(0, 6)
                                            .map((line) => {
                                                const [label, ...parts] =
                                                    line.split("|");
                                                return {
                                                    label: label.trim(),
                                                    detail: parts
                                                        .join("|")
                                                        .trim(),
                                                };
                                            }),
                                    })
                                }
                                rows={7}
                            />
                        </label>
                    )}
                    {(slide.layout === "table" || slide.layout === "flow") && (
                        <label>
                            对照表 · 第一行为表头，用 | 分列
                            <textarea
                                aria-label="幻灯片表格"
                                value={
                                    slide.table?.headers.length
                                        ? [
                                              slide.table.headers,
                                              ...slide.table.rows,
                                          ]
                                              .map((r) => r.join(" | "))
                                              .join("\n")
                                        : ""
                                }
                                onChange={(e) => {
                                    const rows = e.target.value
                                        .split("\n")
                                        .slice(0, 7)
                                        .map((r) =>
                                            r
                                                .split("|")
                                                .slice(0, 5)
                                                .map((c) => c.trim()),
                                        );
                                    edit({
                                        table: {
                                            headers: rows[0],
                                            rows: rows.slice(1),
                                        },
                                    });
                                }}
                                rows={6}
                            />
                        </label>
                    )}
                    <label>
                        本页结论
                        <textarea
                            value={slide.takeaway || ""}
                            maxLength={220}
                            onChange={(e) => edit({ takeaway: e.target.value })}
                            rows={2}
                        />
                    </label>
                    <button
                        className="button secondary"
                        onClick={() => setFiguresOpen(true)}
                    >
                        <ImagePlus size={14} />
                        选择原文图版
                    </button>
                    <label>
                        要点 · 每行一条
                        <textarea
                            value={slide.bullets.join("\n")}
                            onChange={(e) =>
                                edit({
                                    bullets: e.target.value
                                        .split("\n")
                                        .slice(0, 5),
                                })
                            }
                            rows={9}
                        />
                    </label>
                    <label>
                        引用 · 每行一条
                        <textarea
                            value={slide.citations.join("\n")}
                            onChange={(e) =>
                                edit({
                                    citations: e.target.value
                                        .split("\n")
                                        .filter(Boolean),
                                })
                            }
                            rows={3}
                        />
                    </label>
                    <div className="inline">
                        {slide.citations.map((c, i) => (
                            <button
                                key={i}
                                className="text-button"
                                onClick={() => {
                                    const m = c.match(
                                        /\[\[([SCV]):([^\]]+)\]\]/,
                                    );
                                    if (m) onEvidence(m[1], m[2]);
                                }}
                            >
                                依据 {i + 1}
                            </button>
                        ))}
                    </div>
                    <label className="button secondary slide-upload">
                        <ImagePlus size={14} />
                        添加配图
                        <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            hidden
                            onChange={async (e) => {
                                const file = e.target.files?.[0];
                                if (!file) return;
                                try {
                                    const form = new FormData();
                                    form.append("file", file);
                                    const a = await api<Asset>(
                                        `/projects/${projectId}/assets`,
                                        { method: "POST", body: form },
                                    );
                                    edit({ image_asset_id: a.id });
                                } catch (e) {
                                    onError((e as Error).message);
                                }
                            }}
                        />
                    </label>
                    {slide.image_asset_id && (
                        <button
                            className="text-button"
                            onClick={() => edit({ image_asset_id: null })}
                        >
                            移除图片
                        </button>
                    )}
                </aside>
            </div>
            {figuresOpen && (
                <FigurePicker
                    projectId={projectId}
                    sourceIds={
                        (record.version.fields.source_ids as string[]) || []
                    }
                    onClose={() => setFiguresOpen(false)}
                    onSelect={(f) =>
                        edit({
                            image_asset_id: f.asset_id,
                            image_caption: f.label,
                            citations: [
                                ...new Set([...slide.citations, f.citation]),
                            ],
                        })
                    }
                />
            )}
        </div>
    );
}
