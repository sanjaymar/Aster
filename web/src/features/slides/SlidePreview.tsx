import type { Deck, Slide } from "./SlidesPage";
export const layouts = {
    cover: "封面",
    bullets: "要点",
    flow: "方法流程",
    table: "结果对照",
    figure: "原文图解",
    comparison: "双栏比较",
    closing: "讨论与总结",
};
export function SlidePreview({
    slide,
    deck,
    page,
}: {
    slide: Slide;
    deck: Deck;
    page: number;
    projectId: string;
}) {
    const plain = (s: string) => s.replace(/\[\[[^\]]+\]\]/g, "");
    const picture = slide.image_asset_id ? (
        <figure>
            <img
                src={`/api/assets/${slide.image_asset_id}?inline=true`}
                alt="原文配图"
            />
            {slide.image_caption && (
                <figcaption>{slide.image_caption}</figcaption>
            )}
        </figure>
    ) : null;
    const table = slide.table?.headers.length ? (
        <table>
            <thead>
                <tr>
                    {slide.table.headers.map((h, i) => (
                        <th key={i}>{h}</th>
                    ))}
                </tr>
            </thead>
            <tbody>
                {slide.table.rows.map((r, i) => (
                    <tr key={i}>
                        {r.map((c, j) => (
                            <td key={j}>{c}</td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </table>
    ) : null;
    const bullets = (
        <ul>
            {slide.bullets.map((b, i) => (
                <li key={i}>{plain(b)}</li>
            ))}
        </ul>
    );
    return (
        <div
            className={`slide-preview ${deck.theme} layout-${slide.layout || "bullets"}`}
        >
            <div className="sp-accent" />
            <h2>{slide.title}</h2>
            {slide.subtitle && <p className="sp-subtitle">{slide.subtitle}</p>}
            <div className="sp-content">
                {slide.layout === "cover" ? (
                    <>
                        <div className="sp-cover-title">
                            <strong>{deck.title}</strong>
                            {bullets}
                        </div>
                        <div className="sp-cover-mark">
                            RESEARCH
                            <br />
                            BRIEFING
                        </div>
                    </>
                ) : slide.layout === "flow" && slide.steps?.length ? (
                    <>
                        <ol className="sp-flow">
                            {slide.steps.map((s, i) => (
                                <li key={i}>
                                    <b>{String(i + 1).padStart(2, "0")}</b>
                                    <span>
                                        <strong>{s.label}</strong>
                                        <small>{s.detail}</small>
                                    </span>
                                </li>
                            ))}
                        </ol>
                        {!!(table || picture || slide.bullets.length) && (
                            <div className="sp-flow-side">
                                {table}
                                {picture || (!table && bullets)}
                            </div>
                        )}
                    </>
                ) : slide.layout === "table" && table ? (
                    <div className="sp-table">
                        {table}
                        <p>{slide.bullets.slice(0, 2).join("；")}</p>
                    </div>
                ) : picture ? (
                    <>
                        {!!slide.bullets.length && (
                            <div className="sp-figure-notes">{bullets}</div>
                        )}
                        {picture}
                    </>
                ) : slide.layout === "comparison" ? (
                    <div className="sp-compare">
                        {[0, 1].map((col) => (
                            <div key={col}>
                                <ul>
                                    {slide.bullets
                                        .filter((_, i) => i % 2 === col)
                                        .map((b, i) => (
                                            <li key={i}>{plain(b)}</li>
                                        ))}
                                </ul>
                            </div>
                        ))}
                    </div>
                ) : slide.layout === "closing" ? (
                    <div className="sp-closing">
                        <strong>{slide.takeaway || slide.title}</strong>
                        {bullets}
                    </div>
                ) : (
                    bullets
                )}
            </div>
            {slide.takeaway &&
                slide.layout !== "cover" &&
                slide.layout !== "closing" && (
                    <div className="sp-takeaway">{slide.takeaway}</div>
                )}
            <footer>
                <span>{deck.title}</span>
                <span>{String(page).padStart(2, "0")}</span>
            </footer>
        </div>
    );
}
