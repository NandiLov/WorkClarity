from typing import Any
#Any allows individual shift records to contain different fields without us imposing an unfinished data contract.
from pydantic import BaseModel, Field


class ShiftCalculationRequest(BaseModel):
    """Request body for validating shifts and calculating earnings."""

    worker_id: str #Identifies the worker whose shifts are being processed.

    shifts: list[dict[str, Any]] = Field(default_factory=list) #Holds the submitted shift records.

    rules: dict[str, Any] | None = None #Allows optional calculation settings.

    known_locations: list[str] | None = None #Provides locations for commute validation

    include_unconfirmed: bool = False #Controls whether unconfirmed shifts participate in conflict checks.
