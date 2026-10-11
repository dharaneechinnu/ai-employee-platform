"""AI Employee request and response bodies."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.ai_employee import EmployeeStatus

# A safety stop. An AI that gets confused can loop - think, call a tool,
# fail, think again - and every pass costs money. After this many steps
# it stops and reports that it could not finish.
DEFAULT_MAX_STEPS = 15


class GuidedInstructions(BaseModel):
    """Small, answerable questions instead of one empty text box.

    The users are sales, HR and operations people. Writing good model
    instructions is a skill; "be helpful" produces a bad worker and the
    user blames the product. Answering five concrete questions does not.
    """

    what_it_does: str = Field(min_length=1, max_length=2000)
    what_it_must_never_do: str | None = Field(default=None, max_length=2000)
    tone: str | None = Field(default=None, max_length=200)
    when_to_ask_a_human: str | None = Field(default=None, max_length=1000)
    what_good_looks_like: str | None = Field(default=None, max_length=1000)


class EmployeeConfig(BaseModel):
    """Everything that gets frozen into a version."""

    guided: GuidedInstructions | None = None
    # The escape hatch for expert users. When set it replaces the text
    # built from the guided answers rather than being appended to it.
    raw_instructions: str | None = Field(default=None, max_length=20000)

    model: str = "gemini-flash"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_steps: int = Field(default=DEFAULT_MAX_STEPS, ge=1, le=100)
    enabled_tools: list[str] = Field(default_factory=list)


class CreateEmployeeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    job_title: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    avatar: str | None = Field(default=None, max_length=20)
    config: EmployeeConfig
    template_id: uuid.UUID | None = None


class UpdateEmployeeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    job_title: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    avatar: str | None = Field(default=None, max_length=20)
    config: EmployeeConfig | None = None


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    job_title: str | None
    department: str | None
    avatar: str | None
    status: EmployeeStatus
    version_no: int
    config: EmployeeConfig
    created_at: datetime


class EmployeeListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    job_title: str | None
    department: str | None
    avatar: str | None
    status: EmployeeStatus


class EmployeeListResponse(BaseModel):
    """Carries the quota alongside the list so the UI can show
    "3 of 5 used" without a second request."""

    items: list[EmployeeListItem]
    used: int
    limit: int


class VersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_no: int
    config: dict[str, Any]
    created_at: datetime


class PromptPreviewResponse(BaseModel):
    """The exact text the model will receive.

    Without this the employee is a black box: something behaves oddly
    and the user has no way to see why. With it they can spot a bad
    instruction themselves.
    """

    system_prompt: str
    character_count: int


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    department: str | None
    config: dict[str, Any]
    is_platform_template: bool


class CreateTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    employee_id: uuid.UUID
