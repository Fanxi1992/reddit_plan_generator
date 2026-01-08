from __future__ import annotations

import json
import os
from pathlib import Path

from google import genai

from backend.chat_history import append_message, get_history_path, load_history


MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-3-pro-preview")


def load_prompts() -> dict[str, str]:
    prompts_file = os.environ.get("PROMPTS_FILE")
    if not prompts_file:
        return {}
    try:
        raw = json.loads(Path(prompts_file).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
    except Exception:
        return {}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def normalize_subreddit(raw: str) -> str:
    name = (raw or "").strip()
    if name.lower().startswith("r/"):
        name = name[2:]
    return f"r/{name.strip()}"


def render_prompt(
    template: str, *, subreddit_name: str, product_brief: str, subreddit_dossier: str, corpus_excerpt: str
) -> str:
    return (
        template.replace("{{subreddit_name}}", subreddit_name)
        .replace("{{product_brief}}", product_brief)
        .replace("{{subreddit_dossier}}", subreddit_dossier)
        .replace("{{corpus_excerpt}}", corpus_excerpt)
    )


def main() -> int:
    run_dir = Path.cwd()
    config_path = run_dir / "run_config.json"
    if not config_path.is_file():
        print("Error: missing run_config.json")
        return 1

    config = read_json(config_path)
    subreddit_name = normalize_subreddit(str(config.get("target_subreddit") or ""))

    prompts = load_prompts()
    template = (prompts.get("post_draft_prompt") or "").strip()
    if not template:
        print("Error: post_draft_prompt is empty.")
        return 1

    brief_path = run_dir / "product_brief.md"
    dossier_path = run_dir / "subreddit_dossier.md"
    excerpt_path = run_dir / "corpus_excerpt.md"

    needs_product_brief = "{{product_brief}}" in template
    needs_subreddit_dossier = "{{subreddit_dossier}}" in template
    needs_corpus_excerpt = "{{corpus_excerpt}}" in template

    missing: list[str] = []
    if needs_product_brief and not brief_path.is_file():
        missing.append(brief_path.name)
    if needs_subreddit_dossier and not dossier_path.is_file():
        missing.append(dossier_path.name)
    if needs_corpus_excerpt and not excerpt_path.is_file():
        missing.append(excerpt_path.name)
    if missing:
        print(f"Error: missing required artifacts for post_draft_prompt: {', '.join(missing)}")
        return 1

    product_brief = read_text(brief_path) if needs_product_brief else ""
    subreddit_dossier = read_text(dossier_path) if needs_subreddit_dossier else ""
    corpus_excerpt = read_text(excerpt_path) if needs_corpus_excerpt else ""

    prompt = render_prompt(
        template,
        subreddit_name=subreddit_name,
        product_brief=product_brief,
        subreddit_dossier=subreddit_dossier,
        corpus_excerpt=corpus_excerpt,
    )

    history_path = get_history_path(run_dir)
    history = load_history(history_path)

    client = genai.Client()
    chat = client.chats.create(model=MODEL_ID, history=history)
    response = chat.send_message(
        prompt,
        config={
            "temperature": 0.25,
            "max_output_tokens": 4000,
        },
    )
    text = response.text or ""

    out_path = run_dir / "post_v1.md"
    out_path.write_text(text.strip() + "\n", encoding="utf-8")

    append_message(history_path, role="user", text=f"[Stage] Post v1 drafted for {subreddit_name}.")
    append_message(history_path, role="model", text=text.strip())

    print(f"[ok] Wrote {out_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
