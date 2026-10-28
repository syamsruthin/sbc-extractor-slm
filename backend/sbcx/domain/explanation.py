from typing import Literal

from pydantic import BaseModel, Field


class ScenarioText(BaseModel):
    scenario: str
    text: str


class Explanation(BaseModel):
    headline: str
    key_points: list[str] = Field(min_length=1, max_length=6)
    scenarios: list[ScenarioText]
    watch_out: list[str] = []
    assumptions: list[str] = []
    disclaimer: str


class GroundingReport(BaseModel):
    ok: bool
    numbers_checked: int
    violations: list[str] = []
    policy_violations: list[str] = []
    claim_violations: list[str] = []  # superlatives that contradict the computed rankings


class ExplanationRecord(BaseModel):
    content: Explanation
    source: Literal["llm", "llm_retry", "template"]
    grounding: GroundingReport
    model: str | None = None
    prompt_version: str
