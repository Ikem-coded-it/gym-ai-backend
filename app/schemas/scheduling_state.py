from typing import Literal

from pydantic import BaseModel, Field


ScheduleStep = Literal[
    "idle",
    "pick_day",
    "pick_muscle_group",
    "pick_exercises",
    "review",
]

ScheduleFlow = Literal["idle", "schedule_workout"]


class SchedulingDraft(BaseModel):
    day: str | None = None
    muscle_group: str | None = None


class SchedulingState(BaseModel):
    flow: ScheduleFlow = "idle"
    step: ScheduleStep = "idle"
    draft: SchedulingDraft = Field(default_factory=SchedulingDraft)

    @classmethod
    def idle(cls) -> "SchedulingState":
        return cls()

    def is_scheduling(self) -> bool:
        return self.flow == "schedule_workout" and self.step != "idle"
