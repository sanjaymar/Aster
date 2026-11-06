from dataclasses import dataclass


@dataclass(frozen=True)
class Extension:
    key: str
    label: str
    artifact_kinds: tuple[str, ...]


EXTENSIONS = {
    "research": Extension("research", "研究文献", ("note", "deck")),
    "general": Extension("general", "自定义知识库", ("note", "deck")),
}
