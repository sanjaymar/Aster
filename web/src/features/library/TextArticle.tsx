import type { Annotation } from "../../shared/api";
export function TextArticle({
    text,
    annotations,
    fontSize,
    page,
}: {
    text: string;
    annotations: Annotation[];
    fontSize: number;
    page: number;
}) {
    function marked(value: string, offset: number) {
        const chars = Array.from(value),
            end = offset + chars.length;
        const ranges = annotations.filter(
            (a) => a.start_offset < end && a.end_offset > offset,
        );
        const cuts = [
            ...new Set([
                0,
                chars.length,
                ...ranges.flatMap((a) => [
                    Math.max(0, a.start_offset - offset),
                    Math.min(chars.length, a.end_offset - offset),
                ]),
            ]),
        ].sort((a, b) => a - b);
        return cuts.slice(0, -1).map((start, index) => {
            const stop = cuts[index + 1],
                annotation = ranges.find(
                    (a) =>
                        a.start_offset <= start + offset &&
                        a.end_offset >= stop + offset,
                ),
                content = chars.slice(start, stop).join("");
            return annotation ? (
                <mark
                    key={start}
                    title={annotation.comment || annotation.quote}
                >
                    {content}
                </mark>
            ) : (
                <span key={start}>{content}</span>
            );
        });
    }
    return (
        <article className="article-prose" style={{ fontSize }}>
            {Array.from(text.matchAll(/[^\n]+(?:\n(?!\n)[^\n]+)*/g)).map(
                (match) => {
                    const start = Array.from(text.slice(0, match.index)).length,
                        header = /^(#{1,4}) (.+)$/s.exec(match[0]);
                    return (
                        <section id={`reading-${page}-${start}`} key={start}>
                            {header ? (
                                <h2 className={`article-h${header[1].length}`}>
                                    {marked(
                                        header[2],
                                        start + header[1].length + 1,
                                    )}
                                </h2>
                            ) : (
                                <p>{marked(match[0], start)}</p>
                            )}
                        </section>
                    );
                },
            )}
        </article>
    );
}
