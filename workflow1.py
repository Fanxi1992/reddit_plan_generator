from __future__ import annotations

import json
import os
from pathlib import Path

from google import genai

from backend.chat_history import append_message, get_history_path, load_history

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------

MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

client = genai.Client()

# -------------------------------------------------------------------------
# Prompt & Context
# -------------------------------------------------------------------------

SYSTEM_PROMPT = """
You are an expert Reddit Marketing Specialist.
Your core competencies include:
1. Deep understanding of niche markets and subcultures on Reddit.
2. Mastery of Reddiquette and anti-marketing mechanisms.
3. Ability to write high-value, native-feeling content, avoiding overt advertising language.

My business helps clients formulate Reddit promotion schemes for their specific products.
Your task is to act as my intelligent agent, assisting me through the entire process: research, subreddit filtering, and copywriting.

CURRENT STAGE:
Do not generate the full plan yet. Your priority right now is to fully understand the product background I provide.
"""

DEFAULT_PRODUCT_CONTEXT = """
[Client Product Data]
Product Name: DeepFocus
Type: Chrome/Edge Browser Extension + Lightweight Desktop Client
Core Features:
1. "Flow Mode": One-click blocking of all social media and non-work-related sites.
2. "FOMO Killer": While blocked, if Slack or Discord receives new messages, AI silently scrapes them in the background and generates a "Non-Urgent Summary". When you finish work, you only see the summary, no need to scroll through chat history.
3. Privacy First: All data processing is done locally; nothing is uploaded to the cloud.
Target Audience: Remote full-stack developers, grad students writing theses, knowledge workers with ADHD tendencies.
Competitors: Forest, Cold Turkey, Opal.
Key Differentiator: Competitors only "force lock" your device; we provide "peace of mind" (blocking distractions while catching missed info for you).
"""

DEFAULT_PHASE1_PROMPT = (
    SYSTEM_PROMPT.strip()
    + "\n\n{{product_context}}\n\n"
    + "Please confirm you understand the product and your role. "
    + "Briefly summarize the core selling point of the product described above in one sentence (in English), "
    + "and confirm you are ready for the next step."
)


def load_prompts() -> dict[str, str]:
    """Load per-run prompts from PROMPTS_FILE (JSON), if provided."""
    prompts_file = os.environ.get("PROMPTS_FILE")
    if not prompts_file:
        return {}

    try:
        raw = json.loads(Path(prompts_file).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
    except Exception as e:
        print(f"Warning: Failed to load PROMPTS_FILE='{prompts_file}': {e}")
        return {}


def render_prompt(template: str, *, product_context: str) -> str:
    return template.replace("{{product_context}}", product_context)


def load_product_context(default_text: str) -> str:
    path = os.environ.get("PRODUCT_CONTEXT_FILE")
    candidates = [
        path,
        os.path.join(os.path.dirname(__file__), "inputs", "product_context.md"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return Path(candidate).read_text(encoding="utf-8").strip()
    return default_text.strip()


def main() -> int:
    product_context = load_product_context(DEFAULT_PRODUCT_CONTEXT)
    prompts = load_prompts()

    phase1_template = prompts.get("phase1_prompt", DEFAULT_PHASE1_PROMPT)
    initial_input = render_prompt(phase1_template, product_context=product_context)

    print("Connecting to Gemini Chat API...")
    try:
        run_dir = Path.cwd()
        history_path = get_history_path(run_dir)
        history = load_history(history_path)

        chat = client.chats.create(model=MODEL_ID, history=history)
        response = chat.send_message(initial_input)
        response_text = response.text or ""

        append_message(history_path, role="user", text=initial_input)
        append_message(history_path, role="model", text=response_text)

        print("\n" + "=" * 50)
        print("Phase 1 Complete")
        print("=" * 50)
        print("\nAI Response:")
        print(response_text)
        print(f"\n[Info] Chat history appended: {history_path}")
        return 0
    except Exception as e:
        print(f"\nError: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

