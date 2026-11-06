from typing import Literal
from pydantic import Field
from aster.domain.schemas import Input


class Step(Input):
    label: str = Field(max_length=80)
    detail: str = Field(default="", max_length=180)


class Table(Input):
    headers: list[str] = Field(default_factory=list, max_length=5)
    rows: list[list[str]] = Field(default_factory=list, max_length=6)


class Slide(Input):
    title: str = Field(min_length=1, max_length=100)
    bullets: list[str] = Field(default_factory=list, max_length=5)
    notes: str = Field(default="", max_length=3000)
    citations: list[str] = Field(default_factory=list, max_length=10)
    image_asset_id: str | None = None
    layout: Literal["cover", "bullets", "flow", "table", "figure", "comparison", "closing"] = (
        "bullets"
    )
    subtitle: str = Field(default="", max_length=180)
    takeaway: str = Field(default="", max_length=220)
    steps: list[Step] = Field(default_factory=list, max_length=6)
    table: Table = Field(default_factory=Table)
    image_caption: str = Field(default="", max_length=600)


class Deck(Input):
    title: str = Field(min_length=1, max_length=200)
    theme: Literal["academic", "paper", "ink"] = "academic"
    slides: list[Slide] = Field(min_length=1, max_length=30)


class DeckSave(Deck):
    expected_revision: int | None = Field(default=None, ge=1)
