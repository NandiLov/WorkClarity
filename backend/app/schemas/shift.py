
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ShiftCalculationRequest(BaseModel):
    """Request body for validating shifts and calculating earnings."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str

    shifts: list[dict[str, Any]] = Field(default_factory=list)

    include_unconfirmed: bool = False
