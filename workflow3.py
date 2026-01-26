from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path

import pandas as pd
import praw
import prawcore
from dotenv import load_dotenv
from google import genai

from backend.chat_history import append_message, get_history_path, load_history

# ==========================================
# 1) Config & Auth
# ==========================================

load_dotenv()

MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-3-pro-preview")
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


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


def render_prompt(template: str, *, rules_context: str) -> str:
    return template.replace("{{rules_context}}", rules_context)


PROMPTS = load_prompts()

if not os.getenv("REDDIT_CLIENT_ID"):
    print("Error: Missing Reddit credentials in .env")
    raise SystemExit(1)


def get_latest_file(pattern: str) -> Path | None:
    matches = list(Path.cwd().glob(pattern))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


# Load LATEST Raw Subreddit JSON (Phase 2 output)
try:
    latest_json_file = get_latest_file("raw_subreddits_*.json")
    if not latest_json_file:
        raise FileNotFoundError("No 'raw_subreddits_*.json' found.")

    target_subreddits = json.loads(latest_json_file.read_text(encoding="utf-8"))
    if not isinstance(target_subreddits, list):
        raise ValueError("raw_subreddits json must be a JSON array.")
    print(f"Loaded {len(target_subreddits)} subreddits from: {latest_json_file.name}")
except Exception as e:
    print(f"Error: {e}")
    raise SystemExit(1)


reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=f"script:market_research:v2.0 (by /u/{os.getenv('REDDIT_USERNAME', 'bot')})",
    username=os.getenv("REDDIT_USERNAME"),
    password=os.getenv("REDDIT_PASSWORD"),
)

client = genai.Client()


# ==========================================
# 2) PRAW scraping & formatting
# ==========================================

def fetch_and_format_rules(sub_list: list[str]) -> str:
    print(f"\nStarting PRAW audit for {len(sub_list)} communities...\n")

    excel_data: list[dict[str, object]] = []
    ai_context_buffer = "Here is the detailed Rules & Data report for the proposed subreddits:\n\n"

    for index, raw_name in enumerate(sub_list, 1):
        sub_name = str(raw_name).strip()
        if not sub_name:
            continue

        print(f"[{index}/{len(sub_list)}] Scanning r/{sub_name}...", end="", flush=True)

        row: dict[str, object] = {
            "Subreddit": sub_name,
            "URL": f"https://www.reddit.com/r/{sub_name}/",
            "Subscribers": 0,
            "Status": "",
            "Has_Rules": "No",
            "Rules_Raw": "",
        }

        sub_ai_block = f"### Subreddit: r/{sub_name}\n"

        try:
            subreddit = reddit.subreddit(sub_name)

            subs_count = int(subreddit.subscribers or 0)
            row["Subscribers"] = subs_count

            sub_ai_block += "- Status: Active\n"
            sub_ai_block += f"- Subscribers: {subs_count}\n"
            sub_ai_block += "- Rules:\n"

            rule_list = list(subreddit.rules)
            row["Status"] = "Active"

            if rule_list:
                row["Has_Rules"] = "Yes"
                formatted_rules_excel: list[str] = []

                for idx, rule in enumerate(rule_list, 1):
                    title = getattr(rule, "short_name", "No Title")
                    desc = getattr(rule, "description", "") or ""

                    formatted_rules_excel.append(f"{idx}. {title}")

                    sub_ai_block += f"  {idx}. {title}\n"
                    if desc.strip():
                        clean_desc = desc.strip().replace("\n", " ")
                        if len(clean_desc) > 300:
                            clean_desc = clean_desc[:300] + "..."
                        sub_ai_block += f"     Description: {clean_desc}\n\n"
                    else:
                        sub_ai_block += "\n"

                row["Rules_Raw"] = "\n".join(formatted_rules_excel)
            else:
                sub_ai_block += "  (No structured rules found)\n"
                row["Rules_Raw"] = "None"

            print(" OK")

        except prawcore.exceptions.NotFound:
            row["Status"] = "404 Not Found"
            sub_ai_block += "- Status: Does Not Exist (404)\n"
            print(" 404")
        except prawcore.exceptions.Forbidden:
            row["Status"] = "403 Forbidden"
            sub_ai_block += "- Status: Private/Banned (403)\n"
            print(" 403")
        except Exception as e:
            row["Status"] = f"Error: {e}"
            sub_ai_block += f"- Status: Error ({e})\n"
            print(f" Error ({e})")

        excel_data.append(row)
        ai_context_buffer += sub_ai_block
        ai_context_buffer += "\n" + "-" * 40 + "\n\n"

    df = pd.DataFrame(excel_data).sort_values(by="Subscribers", ascending=False)
    excel_filename = f"Phase3_Subreddit_Audit_{TIMESTAMP}.xlsx"
    df.to_excel(excel_filename, index=False)
    print(f"\nExcel Audit Report saved: {excel_filename}")

    return ai_context_buffer


# ==========================================
# 3) Gemini: filtering & strategy
# ==========================================

DEFAULT_PHASE3_PROMPT = """
{{rules_context}}

### TASK: Phase 3 - Filtering & Strategy (The Pivot)

You have just received the REAL-WORLD audit data (above) for the subreddits you brainstormed.
Some may not exist, some may be too small, and some may have strict rules against self-promotion.

Please perform the following:

1.  The Filter Logic: Briefly explain your filtering criteria based on the data (e.g., removing banned subs, avoiding subs with "No Ads" rules unless we use a specific strategy, prioritizing high traffic).
2.  The Final Selection: Select the Top 5 most promising subreddits from the list above.
3.  Section 2 of the Marketing Plan: Write the "Community Strategy" section. For EACH of the 5 selected subreddits, explain:
    - Why selected: (Traffic + Relevance)
    - The Angle: How to approach it without violating its specific rules (Reference the specific rule number if applicable).

IMPORTANT:
At the very end, output the names of the Final 5 subreddits in a STRICT JSON ARRAY for the next script.
Example:
```json
["productivity", "webdev", "SaaS", "SideProject", "coding"]

```
"""


def run_phase3_filter(*, history_path: Path, history: list[dict[str, object]], rules_context: str) -> str:
    print("\nSending PRAW audit data to Gemini for Phase 3 filtering...")

    template = PROMPTS.get("phase3_prompt", DEFAULT_PHASE3_PROMPT)
    phase3_prompt = render_prompt(template, rules_context=rules_context)

    chat = client.chats.create(model=MODEL_ID, history=history)
    response = chat.send_message(phase3_prompt)
    full_response = response.text or ""

    append_message(history_path, role="user", text=phase3_prompt)
    append_message(history_path, role="model", text=full_response)

    return full_response


def main() -> int:
    run_dir = Path.cwd()
    history_path = get_history_path(run_dir)
    history = load_history(history_path)
    if not history:
        print(f"Error: missing chat history at '{history_path}'. Run workflow1.py and workflow2.py first.")
        return 1

    rules_context = fetch_and_format_rules([str(s) for s in target_subreddits])
    full_response = run_phase3_filter(history_path=history_path, history=history, rules_context=rules_context)

    json_match = re.search(r"```json\s*(\[.*?\])\s*```", full_response, re.DOTALL)
    if json_match:
        final_list = json.loads(json_match.group(1))
        final_json_filename = f"final_subreddits_{TIMESTAMP}.json"
        Path(final_json_filename).write_text(
            json.dumps(final_list, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        print(f"[File Created] '{final_json_filename}' with {len(final_list)} targets.")
    else:
        print("Warning: Could not auto-extract final JSON list.")

    report_text = re.sub(r"```json\s*\[.*?\]\s*```", "", full_response, flags=re.DOTALL).strip()
    strategy_filename = f"project_part2_strategy_{TIMESTAMP}.md"
    Path(strategy_filename).write_text(report_text + "\n", encoding="utf-8")
    print(f"[File Created] '{strategy_filename}'.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

