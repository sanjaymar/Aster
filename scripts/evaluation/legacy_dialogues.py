"""Create versioned template scenarios, explicitly not an expert QA benchmark."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
papers = json.loads((root / "eval/corpus.json").read_text())["papers"]
dialogs = []
for n in range(30):
    a = papers[n % len(papers)]
    b = papers[(n // len(papers) + n + 1) % len(papers)]
    if a["key"] == b["key"]:
        b = papers[(n + 2) % len(papers)]
    dialogs.append(
        {
            "id": f"dialogue-{n + 1:02d}",
            "type": "template_regression",
            "split": "test" if n >= 20 else "development",
            "turns": [
                {
                    "question": f"请概述《{a['title']}》的核心方法。",
                    "intent": "lookup",
                    "targets": [a["key"]],
                    "clarify": False,
                },
                {
                    "question": "它为什么采用这种设计？只依据原文回答。",
                    "intent": "explain",
                    "targets": [a["key"]],
                    "constraint": "只依据原文回答",
                    "clarify": False,
                },
                {
                    "question": f"与《{b['title']}》相比，两者有什么区别？",
                    "intent": "compare",
                    "targets": [a["key"], b["key"]],
                    "clarify": False,
                },
                {"question": "它的效果更好吗？", "intent": None, "targets": [], "clarify": True},
            ],
        }
    )
out = {
    "name": "multi-turn-templates-v1",
    "annotation": "30 templated four-turn engineering scenarios; not independent expert-reviewed evaluation; do not report as measured real-world QA accuracy",
    "dialogues": dialogs,
}
(root / "eval/dialogues.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(
    "Created", len(dialogs), "template dialogues /", sum(len(d["turns"]) for d in dialogs), "turns"
)
