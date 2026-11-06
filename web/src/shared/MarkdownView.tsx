import { Quote } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

export function MarkdownView({
    text,
    onEvidence,
}: {
    text: string;
    onEvidence: (kind: string, id: string) => void;
}) {
    const content = text.replace(
        /\[\[([SCV]):([a-f0-9]{32})\]\]/g,
        (_, kind, id) =>
            `[${kind !== "V" ? "文献依据" : "记录依据"}](/evidence/${kind}/${id})`,
    );
    return (
        <div className="markdown">
            <Markdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[[rehypeKatex, { strict: false, throwOnError: false }]]}
                components={{
                    a: ({ href, children }) => {
                        const match = href?.match(
                            /^\/evidence\/([SCV])\/([a-f0-9]{32})$/,
                        );
                        return match ? (
                            <button
                                className="citation"
                                onClick={() => onEvidence(match[1], match[2])}
                            >
                                <Quote size={11} />
                                {children}
                            </button>
                        ) : (
                            <a href={href} target="_blank" rel="noreferrer">
                                {children}
                            </a>
                        );
                    },
                }}
            >
                {content}
            </Markdown>
        </div>
    );
}
