from __future__ import annotations

import json
import os
import re
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


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render_prompt(template: str, *, subreddit_name: str, subreddit_meta: str, subreddit_rules: str, corpus_excerpt: str) -> str:
    return (
        template.replace("{{subreddit_name}}", subreddit_name)
        .replace("{{subreddit_meta}}", subreddit_meta)
        .replace("{{subreddit_rules}}", subreddit_rules)
        .replace("{{corpus_excerpt}}", corpus_excerpt)
    )


def extract_json_object(text: str) -> dict | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(1))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def strip_json_block(text: str) -> str:
    return re.sub(r"```json\s*\{.*?\}\s*```", "", text, flags=re.DOTALL).strip()


def main() -> int:
    run_dir = Path.cwd()
    config_path = run_dir / "run_config.json"
    if not config_path.is_file():
        print("Error: missing run_config.json")
        return 1

    config = read_json(config_path)
    sub_name_raw = str(config.get("target_subreddit") or "").strip()
    if sub_name_raw.lower().startswith("r/"):
        sub_name_raw = sub_name_raw[2:]
    subreddit_name = f"r/{sub_name_raw.strip()}"

    meta_path = run_dir / "subreddit_meta.json"
    rules_path = run_dir / "subreddit_rules.md"
    excerpt_path = run_dir / "corpus_excerpt.md"
    if not meta_path.is_file() or not rules_path.is_file() or not excerpt_path.is_file():
        print("Error: missing scrape artifacts. Run paid_workflow1_scrape.py first.")
        return 1

    subreddit_meta = json.dumps(read_json(meta_path), ensure_ascii=False, indent=2)
    subreddit_rules = read_text(rules_path)
    corpus_excerpt = read_text(excerpt_path)

    prompts = load_prompts()
    template = (prompts.get("dossier_prompt") or "").strip()
    if not template:
        print("Error: dossier_prompt is empty.")
        return 1

    prompt = render_prompt(
        template,
        subreddit_name=subreddit_name,
        subreddit_meta=subreddit_meta,
        subreddit_rules=subreddit_rules,
        corpus_excerpt=corpus_excerpt,
    )

    history_path = get_history_path(run_dir)
    history = load_history(history_path)

    client = genai.Client()
    chat = client.chats.create(model=MODEL_ID, history=history)
    response = chat.send_message(
        prompt,
        config={
            "temperature": 0.2,
            "max_output_tokens": 8000,
        },
    )
    full_text = response.text or ""

    dossier_path = run_dir / "subreddit_dossier.md"
    dossier_json_path = run_dir / "subreddit_dossier.json"
    dossier_md = strip_json_block(full_text)
    dossier_path.write_text(dossier_md + "\n", encoding="utf-8")

    dossier_json = extract_json_object(full_text)
    if dossier_json is not None:
        dossier_json_path.write_text(json.dumps(dossier_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    append_message(history_path, role="user", text=f"[Stage] Subreddit dossier generated for {subreddit_name}.")
    append_message(history_path, role="model", text=dossier_md)

    print(f"[ok] Wrote {dossier_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
