from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from .paths import PROMPTS_DIR


Stage = Literal["post_v1", "mod_review", "post_v2", "post_final", "engagement_kit"]

STRATEGIES_DIR = PROMPTS_DIR / "strategies"
STRATEGIES_FILE_FALLBACK = PROMPTS_DIR / "strategies.json"


@dataclass(frozen=True)
class StrategyBrandRules:
    min_mentions: int = 1
    max_mentions: int = 1
    allow_in_title: bool = False
    notes: str | None = None


@dataclass(frozen=True)
class Strategy:
    id: str
    title: str
    description: str
    pov: str | None
    brand: StrategyBrandRules
    title_templates: tuple[str, ...]
    beats: tuple[str, ...]
    draft_template_md: str


def _as_str(value: object, *, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _load_brand(raw: object) -> StrategyBrandRules:
    if not isinstance(raw, dict):
        return StrategyBrandRules()
    min_mentions = raw.get("min_mentions")
    max_mentions = raw.get("max_mentions")
    allow_in_title = raw.get("allow_in_title")
    notes = raw.get("notes")
    try:
        min_i = int(min_mentions) if min_mentions is not None else 1
    except Exception:
        min_i = 1
    try:
        max_i = int(max_mentions) if max_mentions is not None else 1
    except Exception:
        max_i = 1
    return StrategyBrandRules(
        min_mentions=max(0, min_i),
        max_mentions=max(0, max_i),
        allow_in_title=bool(allow_in_title),
        notes=_as_str(notes, default="").strip() or None,
    )


def _parse_strategy(raw: dict[str, Any]) -> Strategy:
    strategy_id = _as_str(raw.get("id")).strip()
    if not strategy_id:
        raise ValueError("Strategy missing id")
    title = _as_str(raw.get("title")).strip() or strategy_id
    description = _as_str(raw.get("description")).strip()
    pov = _as_str(raw.get("pov")).strip() or None
    brand = _load_brand(raw.get("brand"))
    title_templates = tuple(_as_str_list(raw.get("title_templates")))
    beats = tuple(_as_str_list(raw.get("beats")))
    draft_template_md = ""
    draft_lines = raw.get("draft_template_lines")
    if isinstance(draft_lines, list):
        lines: list[str] = []
        for item in draft_lines:
            if item is None:
                lines.append("")
            elif isinstance(item, str):
                lines.append(item.rstrip("\n"))
        draft_template_md = "\n".join(lines).strip()
    else:
        draft_template_md = _as_str(raw.get("draft_template_md")).strip()
    return Strategy(
        id=strategy_id,
        title=title,
        description=description,
        pov=pov,
        brand=brand,
        title_templates=title_templates,
        beats=beats,
        draft_template_md=draft_template_md,
    )


@lru_cache(maxsize=1)
def load_strategies() -> dict[str, Strategy]:
    strategies: dict[str, Strategy] = {}

    if STRATEGIES_DIR.is_dir():
        paths = sorted(p for p in STRATEGIES_DIR.glob("*.json") if p.is_file())
        if not paths:
            raise ValueError(f"No strategy JSON files found in {STRATEGIES_DIR}")
        for path in paths:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"Strategy file must be a JSON object: {path}")
            st = _parse_strategy(raw)
            strategies[st.id] = st
    elif STRATEGIES_FILE_FALLBACK.is_file():
        raw = json.loads(STRATEGIES_FILE_FALLBACK.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("strategies.json must be a JSON array")
        for item in raw:
            if not isinstance(item, dict):
                continue
            st = _parse_strategy(item)
            strategies[st.id] = st
    else:
        raise ValueError(f"Missing strategy catalog: {STRATEGIES_DIR} or {STRATEGIES_FILE_FALLBACK}")

    if "free" not in strategies:
        raise ValueError("Strategy catalog must include id='free'")

    return strategies


def list_strategies() -> list[Strategy]:
    return list(load_strategies().values())


def get_strategy(strategy_id: str | None) -> Strategy:
    strategies = load_strategies()
    if not strategy_id:
        return strategies["free"]
    return strategies.get(strategy_id, strategies["free"])


def validate_strategy_id(strategy_id: str) -> None:
    strategies = load_strategies()
    if strategy_id not in strategies:
        raise ValueError(f"Unknown strategy_id: {strategy_id}")


def _bullet_lines(items: tuple[str, ...]) -> str:
    if not items:
        return ""
    return "\n".join([f"- {x}" for x in items])


def build_strategy_spec(
    *,
    strategy_id: str,
    strategy_notes: str | None,
    stage: Stage,
) -> str:
    st = get_strategy(strategy_id)
    notes = (strategy_notes or "").strip()

    brand_rules = (
        f"- Brand mentions: {st.brand.min_mentions}–{st.brand.max_mentions} times in **Body**\n"
        f"- Brand in title: {'allowed' if st.brand.allow_in_title else 'not allowed'}\n"
    )
    if st.brand.notes:
        brand_rules += f"- Notes: {st.brand.notes}\n"

    header = (
        "# Script Strategy\n\n"
        f"Selected: {st.title} (id: {st.id})\n\n"
        f"{st.description}\n"
    ).strip()

    common = (
        f"{header}\n\n"
        "## Hard Rules\n"
        f"{brand_rules}"
    )

    if notes:
        common += f"\n## Custom Notes\n{notes}\n"

    if stage == "post_v1":
        title_block = _bullet_lines(st.title_templates)
        beats_block = _bullet_lines(st.beats)
        body = common
        if title_block:
            body += f"\n## Title Patterns (choose 1)\n{title_block}\n"
        if beats_block:
            body += f"\n## Beat Sheet (follow this pacing)\n{beats_block}\n"
        if st.draft_template_md:
            body += "\n## Few-shot Draft Template (fill using the run context)\n\n" + st.draft_template_md.strip() + "\n"
        return body.strip()

    if stage == "mod_review":
        return (
            common
            + "\n## Preservation Guidance (this stage)\n"
            "- Evaluate rule compliance first.\n"
            "- When suggesting changes, prefer minimal edits that preserve the selected script’s core premise and pacing.\n"
            "- If something in the script is incompatible with subreddit rules, call it out explicitly and propose a safer alternative that keeps the angle.\n"
        ).strip()

    if stage == "post_v2":
        return (
            common
            + "\n## Preservation Guidance (this stage)\n"
            "- Revise to satisfy mod review **without** flattening the post into a generic product description.\n"
            "- Preserve the selected script’s hook, premise, and overall beat sequence.\n"
            "- Keep brand mention subtle; if you must move it, keep it in Body and keep it to the minimum.\n"
        ).strip()

    if stage == "post_final":
        return (
            common
            + "\n## Preservation Guidance (this stage)\n"
            "- Make the post more Reddit-native and less polished, but do not change the underlying script strategy or angle.\n"
            "- Do not rewrite the premise into a different genre (e.g., from confession to tutorial).\n"
            "- Keep the brand mention count within the hard rules.\n"
        ).strip()

    return common.strip()


def apply_strategy_spec(prompt: str, *, strategy_spec: str) -> str:
    if "{{strategy_spec}}" in prompt:
        return prompt.replace("{{strategy_spec}}", strategy_spec)
    if not strategy_spec.strip():
        return prompt
    return prompt.rstrip() + "\n\n---\n\n" + strategy_spec.strip() + "\n"
