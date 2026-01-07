from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PromptsResponse(BaseModel):
    prompts: dict[str, str]

TopTimeFilter = Literal["day", "week", "month", "year", "all"]


class RunOptions(BaseModel):
    top_time_filter: TopTimeFilter = Field(
        default="month",
        description="Time filter for subreddit.top().",
    )
    top_posts_limit: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Number of top posts to sample from subreddit.top().",
    )
    hot_posts_limit: int = Field(
        default=8,
        ge=0,
        le=25,
        description="Number of hot posts to additionally sample from subreddit.hot().",
    )
    comments_per_post: int = Field(
        default=7,
        ge=1,
        le=15,
        description="Top-level comments to sample per post (approx).",
    )
    replies_per_comment: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Replies to sample per selected top-level comment.",
    )
    comment_reply_depth: int = Field(
        default=2,
        ge=1,
        le=2,
        description="Max comment depth to include (1=top-level only, 2=include one reply level).",
    )


class RunCreateRequest(BaseModel):
    target_subreddit: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Locked target subreddit name (without r/).",
    )
    pre_materials: str = Field(
        ...,
        min_length=1,
        description="Upfront materials (notes/docs). Raw text will NOT be persisted; only the extracted brief is stored.",
    )
    options: RunOptions = Field(
        default_factory=RunOptions,
        description="Sampling options for subreddit corpus scraping.",
    )
    prompt_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Override any of the default prompts by key.",
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
    status: Literal["pending", "running", "succeeded", "failed", "cancelled", "unknown"]
    downloads: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class RunStatusResponse(BaseModel):
    run_id: str
    status: Literal["pending", "running", "succeeded", "failed", "cancelled", "unknown"]
    current_phase: str | None = None
    run_dir: str
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    outputs: dict[str, str] = Field(default_factory=dict)
    downloads: dict[str, str] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: Literal["user", "model"]
    text: str


class ChatHistoryResponse(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatSendRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message to append to the run chat history.")


class ChatSendResponse(BaseModel):
    reply: str
