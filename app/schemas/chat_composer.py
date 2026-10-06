from typing import Literal

from pydantic import BaseModel, Field


class ComposerOption(BaseModel):
    label: str
    value: str


ComposerKind = Literal[
    "day_select",
    "chips",
    "muscle_group_multi_select",
    "exercise_form",
    "confirm",
]

# This is used to communicate with the client to render the UI shortcuts for the active scheduling step.
class ChatComposer(BaseModel):
    """UI shortcuts for the active scheduling step (rendered under the assistant message)."""

    kind: ComposerKind
    options: list[ComposerOption] = Field(default_factory=list)
    suggested_value: str | None = None
