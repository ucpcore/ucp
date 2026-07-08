"""Usage Receipt models (RFC-0007)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ReceiptConsumer(BaseModel):
    model_config = {"extra": "forbid"}

    type: Literal["sidebar", "mcp", "cli", "agent"]
    id: str = Field(min_length=1, max_length=128)
    session_id: Optional[str] = Field(default=None, max_length=64)


class ReceiptRequest(BaseModel):
    model_config = {"extra": "forbid"}

    receipt_version: str = Field(default="0.1.0", max_length=16)
    package_id: str = Field(min_length=1, max_length=256)
    package_generated_at: str = Field(min_length=10, max_length=64)
    consumer: ReceiptConsumer
    claims_cited: list[str] = Field(default_factory=list, max_length=100)
    claims_ignored: list[str] = Field(default_factory=list, max_length=100)
    gaps_needed: list[str] = Field(default_factory=list, max_length=10)
    outcome: Literal["task_completed", "escalated", "failed", "abandoned"]
    submitted_at: Optional[str] = Field(default=None, max_length=64)
    audience: Optional[str] = Field(default=None, max_length=200)
