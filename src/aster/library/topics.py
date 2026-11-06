"""Deterministic cosine clusters and separated topic islands for exploration."""

import numpy as np

COLORS = [
    "#536f99",
    "#4f837a",
    "#a27d50",
    "#85709c",
    "#7d8b54",
    "#a2737e",
    "#57879c",
    "#8a8071",
    "#7b84ad",
    "#839b8a",
]


def group(matrix, vocabulary, nodes):
    n = len(nodes)
    if not n:
        return []
    k = min(10, max(1, round((n / 3) ** 0.5)))
    if not matrix.shape[1]:
        labels, centers = np.zeros(n, dtype=int), np.zeros((1, 0))
    else:
        chosen = [int(np.argmax((matrix @ matrix.T).sum(axis=1)))]
        for _ in range(1, k):
            distances = (matrix @ matrix[chosen].T).max(axis=1)
            distances[chosen] = 2
            chosen.append(int(np.argmin(distances)))
        centers = matrix[chosen].copy()
        for _ in range(30):
            labels = (matrix @ centers.T).argmax(axis=1)
            updated = np.array(
                [
                    matrix[labels == i].mean(axis=0) if (labels == i).any() else centers[i]
                    for i in range(k)
                ]
            )
            updated /= np.maximum(np.linalg.norm(updated, axis=1, keepdims=True), 1e-9)
            if np.allclose(updated, centers):
                break
            centers = updated
    topics = []
    order = sorted(set(labels), key=lambda i: -int((labels == i).sum()))
    for rank, label in enumerate(order):
        indices = np.flatnonzero(labels == label)
        keywords = [vocabulary[i] for i in np.argsort(-centers[label])[:4] if centers[label, i] > 0]
        key, color = f"topic-{rank + 1}", COLORS[rank % len(COLORS)]
        title = " · ".join(keywords[:2]).title() or "待分类"
        topics.append(
            {"id": key, "label": title, "keywords": keywords, "count": len(indices), "color": color}
        )
        center = np.array([(rank % 3) * 420.0, (rank // 3) * 340.0])
        # A stable golden-angle packing keeps individual papers selectable.
        for offset, index in enumerate(indices):
            angle = offset * 2.399963
            radius = 135 * np.sqrt(offset / max(1, len(indices) - 1))
            point = center + np.array([np.cos(angle), np.sin(angle)]) * radius
            nodes[index].update(
                topic=key, color=color, x=round(float(point[0]), 3), y=round(float(point[1]), 3)
            )
    return topics
