from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from google import genai

from backend.chat_history import append_message, get_history_path, load_history


MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")


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
    template: str,
    *,
    subreddit_name: str,
    current_date: str,
    subreddit_rules: str,
    subreddit_dossier: str,
    corpus_excerpt: str,
    post_draft: str,
) -> str:
    return (
        template.replace("{{subreddit_name}}", subreddit_name)
        .replace("{{current_date}}", current_date)
        .replace("{{subreddit_rules}}", subreddit_rules)
        .replace("{{subreddit_dossier}}", subreddit_dossier)
        .replace("{{corpus_excerpt}}", corpus_excerpt)
        .replace("{{post_draft}}", post_draft)
    )


def main() -> int:
    run_dir = Path.cwd()
    config_path = run_dir / "run_config.json"
    if not config_path.is_file():
        print("Error: missing run_config.json")
        return 1

    config = read_json(config_path)
    subreddit_name = normalize_subreddit(str(config.get("target_subreddit") or ""))
    current_date = (str(config.get("current_date") or "")).strip() or datetime.date.today().isoformat()

    rules_path = run_dir / "subreddit_rules.md"
    dossier_path = run_dir / "subreddit_dossier.md"
    excerpt_path = run_dir / "corpus_excerpt.md"
    post_path = run_dir / "post_v1.md"
    if not rules_path.is_file() or not dossier_path.is_file() or not excerpt_path.is_file() or not post_path.is_file():
        print("Error: missing rules/dossier/corpus_excerpt/post_v1 artifacts")
        return 1

    subreddit_rules = read_text(rules_path)
    subreddit_dossier = read_text(dossier_path)
    corpus_excerpt = read_text(excerpt_path)
    post_draft = read_text(post_path)

    prompts = load_prompts()
    template = (prompts.get("mod_review_prompt") or "").strip()
    if not template:
        print("Error: mod_review_prompt is empty.")
        return 1

    prompt = render_prompt(
        template,
        subreddit_name=subreddit_name,
        current_date=current_date,
        subreddit_rules=subreddit_rules,
        subreddit_dossier=subreddit_dossier,
        corpus_excerpt=corpus_excerpt,
        post_draft=post_draft,
    )

    history_path = get_history_path(run_dir)
    history = load_history(history_path)

    client = genai.Client()
    chat = client.chats.create(model=MODEL_ID, history=history)
    response = chat.send_message(
        prompt,
        config={
            "temperature": 0.2,
            "max_output_tokens": 3000,
        },
    )
    text = response.text or ""

    out_path = run_dir / "mod_review.md"
    out_path.write_text(text.strip() + "\n", encoding="utf-8")

    append_message(history_path, role="user", text=f"[Stage] Mod review completed for {subreddit_name}.")
    append_message(history_path, role="model", text=text.strip())

    print(f"[ok] Wrote {out_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
