from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PromptsResponse(BaseModel):
    prompts: dict[str, str]


class RunCreateRequest(BaseModel):
    product_context_md: str = Field(..., min_length=1, description="English product context in Markdown.")
    prompt_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Override any of the default prompts by key (phase1_prompt..phase4_prompt).",
    )
    run_id: str | None = Field(
        default=None,
        description="Optional run id (default: timestamp).",
    )
    wait: bool = Field(
        default=False,
        description="If true, block until the run finishes; if false, return immediately and poll status.",
    )


class RunCreateResponse(BaseModel):
    run_id: str
    status: Literal["pending", "running", "succeeded", "failed", "unknown"]
    downloads: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class RunStatusResponse(BaseModel):
    run_id: str
    status: Literal["pending", "running", "succeeded", "failed", "unknown"]
    current_phase: str | None = None
    run_dir: str
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    outputs: dict[str, str] = Field(default_factory=dict)
    downloads: dict[str, str] = Field(default_factory=dict)

