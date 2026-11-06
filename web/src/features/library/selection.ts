/** Match displayed PDF text to the immutable extracted source without inventing offsets. */
export function locateQuote(
    source: string,
    selection: string,
): { start: number; end: number; quote: string } | null {
    const clean = (text: string) =>
        Array.from(text)
            .filter((char) => !/\s/u.test(char))
            .join("");
    const wanted = clean(selection);
    if (!wanted || wanted.length > 5000) return null;
    const points = Array.from(source),
        positions: number[] = [];
    const normalized = points.filter((char, index) => {
        if (/\s/u.test(char)) return false;
        positions.push(index);
        return true;
    });
    const haystack = normalized.join("");
    // String indexes use UTF-16; convert to code points for the persisted Python offsets.
    const match = haystack.indexOf(wanted);
    if (match < 0 || haystack.indexOf(wanted, match + 1) >= 0) return null;
    const startIndex = Array.from(haystack.slice(0, match)).length;
    const endIndex = startIndex + Array.from(wanted).length - 1;
    const start = positions[startIndex],
        end = positions[endIndex] + 1;
    return { start, end, quote: points.slice(start, end).join("") };
}
