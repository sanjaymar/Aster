"""Breadth-first reading context supplements query-specific retrieval."""

import re
from aster.retrieval.engine import Hit


def broaden(state, source_ids, budget=26000):
    selected = set(source_ids) or {h.evidence.source_id for h in state.hits[:1]}
    candidates = [e for e in state.allowed.values() if e.source_id in selected and e.kind == "C"]
    # Prefer an early, middle and late section; never silently add other papers.
    areas = [
        "abstract|background|introduction",
        "method|material|sample|participant",
        "result|figure|table",
        "discussion|limitation|conclusion",
    ]
    chosen = {h.evidence.id: h for h in state.hits}
    for pattern in areas:
        for source in selected:
            matches = [
                e
                for e in candidates
                if e.source_id == source
                and re.search(pattern, e.section + " " + e.text[:250], re.I)
            ]
            for e in matches[:3]:
                chosen.setdefault(e.id, Hit(e, {"reading": 1.0}))
    total, result = 0, []
    for hit in chosen.values():
        if total + len(hit.evidence.text) <= budget:
            result.append(hit)
            total += len(hit.evidence.text)
    state.hits = result
