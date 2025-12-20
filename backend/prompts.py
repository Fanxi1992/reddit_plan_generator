from __future__ import annotations

import json
from pathlib import Path

from .paths import DEFAULT_PROMPTS_PATH

PROMPT_KEYS: tuple[str, ...] = (
    "phase1_prompt",
    "phase2_prompt",
    "phase3_prompt",
    "phase4_prompt",
)

REQUIRED_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "phase1_prompt": ("{{product_context}}",),
    "phase3_prompt": ("{{rules_context}}",),
    "phase4_prompt": ("{{mined_context}}",),
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


def validate_prompts(prompts: dict[str, str]) -> None:
    for key in PROMPT_KEYS:
        value = prompts.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Prompt '{key}' must be a non-empty string.")

    for key, required_tokens in REQUIRED_PLACEHOLDERS.items():
        for token in required_tokens:
            if token not in prompts[key]:
                raise ValueError(f"Prompt '{key}' must contain placeholder {token}.")


def merge_prompts(default_prompts: dict[str, str], overrides: dict[str, str] | None) -> dict[str, str]:
    merged = dict(default_prompts)
    if overrides:
        for key, value in overrides.items():
            if key not in PROMPT_KEYS:
                raise ValueError(f"Unknown prompt key: {key}")
            if not isinstance(value, str):
                raise ValueError(f"Prompt override '{key}' must be a string.")
            merged[key] = value
    validate_prompts(merged)
    return merged


def write_prompts_file(path: Path, prompts: dict[str, str]) -> None:
    path.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")

