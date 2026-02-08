from __future__ import annotations

import json
from pathlib import Path

from .paths import DEFAULT_PROMPTS_PATH

PROMPT_KEYS: tuple[str, ...] = (
    "brief_prompt",
    "dossier_prompt",
    "post_draft_prompt",
    "mod_review_prompt",
    "revise_prompt",
    "native_polish_prompt",
    "engagement_prompt",
)

REQUIRED_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "brief_prompt": ("{{pre_materials}}",),
    "dossier_prompt": ("{{subreddit_name}}", "{{subreddit_meta}}", "{{subreddit_rules}}", "{{corpus_excerpt}}"),
    # post_draft_prompt placeholders are OPTIONAL to support "client-provided draft" workflows
    # where we don't want to spend tokens injecting large context blocks.
    "post_draft_prompt": (),
    "mod_review_prompt": (
        "{{subreddit_name}}",
        "{{current_date}}",
        "{{subreddit_rules}}",
        "{{subreddit_dossier}}",
        "{{corpus_excerpt}}",
        "{{post_draft}}",
    ),
    "revise_prompt": ("{{subreddit_name}}", "{{current_date}}", "{{mod_review}}", "{{post_draft}}"),
    "native_polish_prompt": ("{{subreddit_name}}", "{{current_date}}", "{{subreddit_dossier}}", "{{post_revision}}"),
    "engagement_prompt": (
        "{{subreddit_name}}",
        "{{current_date}}",
        "{{subreddit_dossier}}",
        "{{corpus_excerpt}}",
        "{{post_final}}",
    ),
}


def load_prompts_file(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Prompts file must be a JSON object.")

    prompts: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        prompts[key] = value
    return prompts


def load_default_prompts(path: Path = DEFAULT_PROMPTS_PATH) -> dict[str, str]:
    prompts = load_prompts_file(path)

    missing = [k for k in PROMPT_KEYS if k not in prompts]
    if missing:
        raise ValueError(f"Default prompts file missing keys: {missing}")

    return {k: prompts[k] for k in PROMPT_KEYS}


def validate_prompts(prompts: dict[str, str], *, skip_keys: set[str] | None = None) -> None:
    skip = skip_keys or set()

    for key in PROMPT_KEYS:
        if key in skip:
            continue
        value = prompts.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Prompt '{key}' must be a non-empty string.")

    for key, required_tokens in REQUIRED_PLACEHOLDERS.items():
        if key in skip:
            continue
        value = prompts.get(key) or ""
        for token in required_tokens:
            if token not in value:
                raise ValueError(f"Prompt '{key}' must contain placeholder {token}.")


def merge_prompts(
    default_prompts: dict[str, str],
    overrides: dict[str, str] | None,
    *,
    skip_keys: set[str] | None = None,
) -> dict[str, str]:
    merged = dict(default_prompts)
    if overrides:
        for key, value in overrides.items():
            if key not in PROMPT_KEYS:
                raise ValueError(f"Unknown prompt key: {key}")
            if not isinstance(value, str):
                raise ValueError(f"Prompt override '{key}' must be a string.")
            merged[key] = value
    validate_prompts(merged, skip_keys=skip_keys)
    return merged


def write_prompts_file(path: Path, prompts: dict[str, str]) -> None:
    path.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")

