from dataclasses import dataclass


@dataclass(frozen=True)
class Extension:
    key: str
    label: str
    artifact_kinds: tuple[str, ...]
    experiments: bool = False


EXTENSIONS = {
    "research": Extension(
        "research", "科研研究", ("note", "draft", "report", "plan", "result", "labnote"), True
    ),
    "general": Extension("general", "通用知识项目", ("note", "draft", "report")),
}
