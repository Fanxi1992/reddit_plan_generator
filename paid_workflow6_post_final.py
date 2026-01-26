from __future__ import annotations

import datetime
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
    template: str, *, subreddit_name: str, current_date: str, subreddit_dossier: str, post_revision: str
) -> str:
    return (
        template.replace("{{subreddit_name}}", subreddit_name)
        .replace("{{current_date}}", current_date)
        .replace("{{subreddit_dossier}}", subreddit_dossier)
        .replace("{{post_revision}}", post_revision)
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

    dossier_path = run_dir / "subreddit_dossier.md"
    post_path = run_dir / "post_v2.md"
    if not dossier_path.is_file() or not post_path.is_file():
        print("Error: missing subreddit_dossier.md or post_v2.md")
        return 1

    subreddit_dossier = read_text(dossier_path)
    post_revision = read_text(post_path)

    prompts = load_prompts()
    template = (prompts.get("native_polish_prompt") or "").strip()
    if not template:
        print("Error: native_polish_prompt is empty.")
        return 1

    prompt = render_prompt(
        template,
        subreddit_name=subreddit_name,
        current_date=current_date,
        subreddit_dossier=subreddit_dossier,
        post_revision=post_revision,
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

    out_path = run_dir / "post_final.md"
    out_path.write_text(text.strip() + "\n", encoding="utf-8")

    append_message(history_path, role="user", text=f"[Stage] Post finalized for {subreddit_name}.")
    append_message(history_path, role="model", text=text.strip())

    print(f"[ok] Wrote {out_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
