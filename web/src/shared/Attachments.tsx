import { Paperclip, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { api, type Asset } from "./api";
import { Spinner } from "./ui";

export function AssetList({
    items,
    onCsv,
    onRemove,
}: {
    items: Asset[];
    onCsv?: (a: Asset) => void;
    onRemove?: (id: string) => void;
}) {
    return (
        <div className="attachments">
            {items.map((a) => (
                <div className="attachment" key={a.id}>
                    {a.media_type.startsWith("image/") ? (
                        <a
                            href={`/api/assets/${a.id}?inline=true`}
                            target="_blank"
                            rel="noreferrer"
                        >
                            <img
                                className="attachment-preview"
                                alt={a.name}
                                src={`/api/assets/${a.id}?inline=true`}
                                loading="lazy"
                            />
                        </a>
                    ) : (
                        <Paperclip size={14} />
                    )}
                    <a href={`/api/assets/${a.id}`}>{a.name}</a>
                    <small>{Math.ceil(a.size / 1024)} KB</small>
                    {a.name.toLowerCase().endsWith(".csv") && onCsv && (
                        <button
                            type="button"
                            className="text-button"
                            onClick={() => onCsv(a)}
                        >
                            查看数据
                        </button>
                    )}
                    {onRemove && (
                        <button
                            type="button"
                            className="icon-button"
                            aria-label={`移除附件 ${a.name}`}
                            onClick={() => onRemove(a.id)}
                        >
                            <X size={13} />
                        </button>
                    )}
                </div>
            ))}
        </div>
    );
}
export function AttachmentPicker({
    projectId,
    items,
    onChange,
    onError,
    onCsv,
}: {
    projectId: string;
    items: Asset[];
    onChange: (assets: Asset[]) => void;
    onError: (message: string) => void;
    onCsv?: (a: Asset) => void;
}) {
    const input = useRef<HTMLInputElement>(null),
        latest = useRef(items);
    latest.current = items;
    const [busy, setBusy] = useState(false);
    async function upload(files: FileList | null) {
        if (!files) return;
        if (latest.current.length + files.length > 50) {
            onError("每份文档最多保存50个附件");
            return;
        }
        setBusy(true);
        try {
            for (const file of Array.from(files)) {
                const form = new FormData();
                form.append("file", file);
                const asset = await api<Asset>(
                    `/projects/${projectId}/assets`,
                    { method: "POST", body: form },
                );
                const next = [...latest.current, asset];
                latest.current = next;
                onChange(next);
            }
        } catch (error) {
            onError((error as Error).message);
        } finally {
            setBusy(false);
            if (input.current) input.current.value = "";
        }
    }
    return (
        <div className="document-attachments">
            <button
                type="button"
                className="text-button"
                disabled={busy}
                onClick={() => input.current?.click()}
            >
                {busy ? <Spinner /> : <Upload size={14} />}添加附件
            </button>
            <input
                ref={input}
                hidden
                aria-label="上传文档附件"
                type="file"
                multiple
                onChange={(e) => void upload(e.target.files)}
            />
            <AssetList
                items={items}
                onCsv={onCsv}
                onRemove={(id) => onChange(items.filter((a) => a.id !== id))}
            />
        </div>
    );
}
