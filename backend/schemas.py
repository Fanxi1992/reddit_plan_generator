from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

TopTimeFilter = Literal["day", "week", "month", "year", "all"]
PostV1Mode = Literal["generate", "client_draft"]
BriefMode = Literal["extract", "raw"]


class PromptsResponse(BaseModel):
    prompts: dict[str, str]


class EffectivePromptsRequest(BaseModel):
    prompt_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Override any of the default prompts by key (same semantics as RunCreateRequest.prompt_overrides).",
    )
    strategy_id: str = Field(
        default="free",
        max_length=64,
        description="Selected script strategy id from /api/strategies (default: free).",
    )
    strategy_notes: str | None = Field(
        default=None,
        description="Optional operator notes to tailor the selected strategy (will be injected as Custom Notes).",
    )
    brief_mode: BriefMode = Field(
        default="extract",
        description="How product_brief.md will be produced at runtime (affects whether brief_prompt is required).",
    )


class StrategyBrandRules(BaseModel):
    min_mentions: int = Field(
        default=1,
        ge=0,
        description="Minimum number of brand mentions in the main post body.",
    )
    max_mentions: int = Field(
        default=1,
        ge=0,
        description="Maximum number of brand mentions in the main post body.",
    )
    allow_in_title: bool = Field(
        default=False,
        description="Whether the brand can appear in the post title.",
    )
    notes: str | None = Field(
        default=None,
        description="Human notes about the brand mention rule.",
    )


class StrategyDef(BaseModel):
    id: str = Field(..., min_length=1, description="Stable strategy id.")
    title: str = Field(..., min_length=1, description="Display title for the operator UI.")
    description: str = Field(default="", description="What this strategy is for.")
    pov: str | None = Field(default=None, description="Suggested POV (e.g. user/founder/either).")
    brand: StrategyBrandRules = Field(default_factory=StrategyBrandRules)
    title_templates: list[str] = Field(default_factory=list)
    beats: list[str] = Field(default_factory=list)
    draft_template_md: str = Field(default="", description="Draft template (markdown).")


class StrategiesResponse(BaseModel):
    strategies: list[StrategyDef] = Field(default_factory=list)


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
        description="Upfront materials (notes/docs). Raw text is persisted to pre_materials.md; only the extracted product_brief.md is used as authoritative chat context.",
    )
    brief_mode: BriefMode = Field(
        default="extract",
        description="How to create product_brief.md. 'extract' summarizes via brief_prompt; 'raw' uses pre_materials verbatim.",
    )
    options: RunOptions = Field(
        default_factory=RunOptions,
        description="Sampling options for subreddit corpus scraping.",
    )
    prompt_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Override any of the default prompts by key.",
    )
    strategy_id: str = Field(
        default="free",
        max_length=64,
        description="Selected script strategy id from /api/strategies (default: free).",
    )
    strategy_notes: str | None = Field(
        default=None,
        description="Optional operator notes to tailor the selected strategy.",
    )
    post_v1_mode: PostV1Mode = Field(
        default="generate",
        description="How to produce post_v1.md. 'generate' uses post_draft_prompt; 'client_draft' uses post_v1_client_draft as-is.",
    )
    post_v1_client_draft: str | None = Field(
        default=None,
        description="Client-provided draft to use as post_v1.md when post_v1_mode is 'client_draft'.",
    )
    stop_after_mod_review: bool = Field(
        default=False,
        description="If true, stop the workflow after mod_review.md is generated (stages 5-7 will be skipped).",
    )
    run_id: str | None = Field(
        default=None,
        description="Optional run id (default: timestamp_subreddit).",
    )
    wait: bool = Field(
        default=False,
        description="If true, block until the run finishes; if false, return immediately and poll status.",
    )

    @model_validator(mode="after")
    def _validate_post_v1_mode(self) -> "RunCreateRequest":
        if self.post_v1_mode == "client_draft":
            if not (self.post_v1_client_draft or "").strip():
                raise ValueError("post_v1_client_draft is required when post_v1_mode is 'client_draft'.")
        return self


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


class RunRestoreResponse(BaseModel):
    run_id: str
    target_subreddit: str
    pre_materials: str
    brief_mode: BriefMode = Field(
        default="extract",
        description="How product_brief.md was produced for this run.",
    )
    prompts: dict[str, str]
    strategy_id: str = Field(
        default="free",
        description="Script strategy id used for this run.",
    )
    strategy_notes: str | None = Field(
        default=None,
        description="Operator notes used for this run.",
    )
    post_v1_mode: PostV1Mode = Field(
        default="generate",
        description="How post_v1.md was produced for this run.",
    )
    post_v1_client_draft: str | None = Field(
        default=None,
        description="Client draft content when post_v1_mode is 'client_draft'.",
    )
    stop_after_mod_review: bool = Field(
        default=False,
        description="If true, the workflow was configured to stop after Mod review.",
    )


class ChatMessage(BaseModel):
    role: Literal["user", "model"]
    text: str


class ChatHistoryResponse(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatSendRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message to append to the run chat history.")


class ChatSendResponse(BaseModel):
    reply: str
