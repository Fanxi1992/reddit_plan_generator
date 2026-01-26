from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path

from google import genai

from backend.chat_history import append_message, get_history_path, load_history

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------

MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

client = genai.Client()


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


PHASE2_PROMPT = """
Great. Now let's move to Phase 2.
Based on the product context and role we established in the previous turn, please perform two tasks in this single response:

### TASK 1: Write Section 1 of the Marketing Plan (The Positioning)
Write a professional "Market Positioning & Audience Analysis" section specifically for this product.
Include:
- **Target Persona Breakdown**: Identify and profile the 3 most relevant user groups for this specific product.
- **Core Pain Points**: What specific problems or needs do these users discuss on Reddit related to this product category?
- **The Strategy**: How should we position this product to resonate with these Reddit communities naturally?
(Keep this section strictly text/markdown).

### TASK 2: Brainstorm Subreddit Candidates (The Raw List)
Based on the personas you just identified, brainstorm at least 30 potential subreddits where we could market this product.
Think broadly and categorize them mentally (but output a flat list):
- **Direct Niches**: Communities directly dedicated to this type of product.
- **Related Interests**: Where the target audience hangs out (even if not discussing the product directly).
- **Competitor/Problem Spaces**: Where people discuss the problems this product solves.

IMPORTANT FORMATTING RULE:
At the very end of your response, provide the list of these 30+ subreddits in a STRICT JSON ARRAY format inside a code block.
Do not include "r/" prefix in the values, just the name.
Example format:
```json
["productivity", "webdev", "adhd", "SaaS"]

```
"""


def main() -> int:
    run_dir = Path.cwd()
    history_path = get_history_path(run_dir)
    history = load_history(history_path)
    if not history:
        print(f"Error: missing chat history at '{history_path}'. Run workflow1.py first.")
        return 1

    prompts = load_prompts()
    phase2_prompt = (prompts.get("phase2_prompt", PHASE2_PROMPT) or "").strip()
    if not phase2_prompt:
        print("Error: phase2 prompt is empty.")
        return 1

    print("Sending Phase 2 instructions (Positioning + List Gen)...")

    try:
        chat = client.chats.create(model=MODEL_ID, history=history)
        response = chat.send_message(phase2_prompt)
        full_response = response.text or ""

        append_message(history_path, role="user", text=phase2_prompt)
        append_message(history_path, role="model", text=full_response)

        print("\n" + "=" * 50)
        print("Phase 2 Complete. Processing outputs...")
        print("=" * 50)

        json_match = re.search(r"```json\s*(\[.*?\])\s*```", full_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            subreddit_list = json.loads(json_str)
            json_filename = f"raw_subreddits_{TIMESTAMP}.json"
            Path(json_filename).write_text(
                json.dumps(subreddit_list, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
            print(f"\n[File Created] '{json_filename}' containing {len(subreddit_list)} subs.")
        else:
            print("\nWarning: Could not auto-extract JSON. Saving full text only.")

        report_text = re.sub(r"```json\s*\[.*?\]\s*```", "", full_response, flags=re.DOTALL).strip()
        report_filename = f"project_part1_positioning_{TIMESTAMP}.md"
        Path(report_filename).write_text(report_text + "\n", encoding="utf-8")
        print(f"[File Created] '{report_filename}'.")
        return 0

    except Exception as e:
        print(f"\nError: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
