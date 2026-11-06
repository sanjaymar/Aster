import { useState } from "react";
import { Search } from "lucide-react";

export function Materials({
    label,
    items,
    selected,
    limit,
    onChange,
}: {
    label: string;
    items: { id: string; title: string }[];
    selected: string[];
    limit: number;
    onChange: (ids: string[]) => void;
}) {
    const [query, setQuery] = useState("");
    const matches = items.filter((item) =>
        item.title.toLowerCase().includes(query.trim().toLowerCase()),
    );
    return (
        <section className="deck-picker" aria-label={`选择汇报${label}`}>
            <div className="deck-picker-heading">
                <span>{label}</span>
                <small>
                    {selected.length} / {limit}
                </small>
            </div>
            <div className="deck-picker-search">
                <Search size={13} />
                <input
                    aria-label={`搜索汇报${label}`}
                    placeholder="搜索标题"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                />
            </div>
            <div className="deck-picker-items">
                {matches.map((item) => (
                    <label key={item.id} title={item.title}>
                        <input
                            type="checkbox"
                            checked={selected.includes(item.id)}
                            disabled={
                                !selected.includes(item.id) &&
                                selected.length >= limit
                            }
                            onChange={(event) =>
                                onChange(
                                    event.target.checked
                                        ? [...selected, item.id]
                                        : selected.filter(
                                              (id) => id !== item.id,
                                          ),
                                )
                            }
                        />
                        <span>{item.title}</span>
                    </label>
                ))}
                {!matches.length && (
                    <p>{query ? "没有匹配的材料" : `还没有${label}`}</p>
                )}
            </div>
        </section>
    );
}
