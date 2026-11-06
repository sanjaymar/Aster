import { ExternalLink } from "lucide-react";
import { type Evidence } from "./api";

import { Modal } from "./ui";

export function EvidenceModal({
    item,
    onClose,
}: {
    item: Evidence;
    onClose: () => void;
}) {
    return (
        <Modal title="引用依据" onClose={onClose} wide>
            <div className="section-heading">
                <div>
                    <span className="eyebrow">
                        {item.kind !== "V" ? "原始资料" : "固定记录版本"}
                    </span>
                    <h2>{item.title}</h2>
                    <p className="muted">
                        版本 {item.version}
                        {item.page
                            ? ` · 第 ${item.page} ${item.content_type && item.content_type !== "application/pdf" ? "段" : "页"}`
                            : ""}
                    </p>
                </div>
                {item.asset_id && (
                    <a
                        className="button secondary"
                        href={`/api/assets/${item.asset_id}?inline=true#page=${item.page || 1}`}
                        target="_blank"
                        rel="noreferrer"
                    >
                        <ExternalLink size={15} />
                        打开原文
                    </a>
                )}
            </div>
            <pre className="source-text">
                {item.content || "本页没有可提取文字，可打开原文查看。"}
            </pre>
            <div className="notice">
                此处展示引用绑定的版本，后续编辑不会改变这条依据。
            </div>
        </Modal>
    );
}
