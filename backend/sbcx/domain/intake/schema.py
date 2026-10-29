"""What the intake LLM returns. Event ids are checked against scenarios.yaml by the validator."""

from pydantic import BaseModel, Field


class DraftEvent(BaseModel):
    event: str = Field(description="An event type id from the catalog")
    count: int = Field(description="Times in a year")
    member: int = Field(description="Household member index; 0 is the person describing")
    quote: str = Field(description="The exact words from the description this event comes from")
    basis: str = Field(description="How the count was worked out, e.g. 'monthly = 12'")


class Unmodeled(BaseModel):
    quote: str = Field(description="The exact words from the description")
    reason: str = Field(
        description="Why it isn't an event, e.g. 'no visits stated' or 'drug tier not stated'"
    )


class UsageDraft(BaseModel):
    events: list[DraftEvent]
    unmodeled: list[Unmodeled]
