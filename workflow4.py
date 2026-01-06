from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

import pandas as pd
import praw
from dotenv import load_dotenv
from google import genai

from backend.chat_history import append_message, get_history_path, load_history

# ==========================================
# 1) Config & init
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


def render_prompt(template: str, *, mined_context: str) -> str:
    return template.replace("{{mined_context}}", mined_context)


PROMPTS = load_prompts()

if not os.getenv("REDDIT_CLIENT_ID"):
    print("Error: Missing Reddit credentials in .env")
    raise SystemExit(1)


def get_latest_file(pattern: str) -> Path | None:
    matches = list(Path.cwd().glob(pattern))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


# Load LATEST Final Subreddit JSON (Phase 3 output)
try:
    latest_final_json = get_latest_file("final_subreddits_*.json")
    if not latest_final_json:
        raise FileNotFoundError("No 'final_subreddits_*.json' found.")

    target_subreddits = json.loads(latest_final_json.read_text(encoding="utf-8"))
    if not isinstance(target_subreddits, list):
        raise ValueError("final_subreddits json must be a JSON array.")
    print(f"Loaded target subreddits from: {latest_final_json.name}")
    print(f"List: {target_subreddits}")
except Exception as e:
    print(f"Error: {e}")
    raise SystemExit(1)


reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=f"script:content_generation:v4.0 (by /u/{os.getenv('REDDIT_USERNAME', 'bot')})",
    username=os.getenv("REDDIT_USERNAME"),
    password=os.getenv("REDDIT_PASSWORD"),
)

client = genai.Client()


# ==========================================
# 2) Helper: comment tree (token-optimized)
# ==========================================

def get_comment_tree_text(submission, limit_top_level: int = 3, max_depth: int = 1) -> str:
    buffer = ""
    submission.comments.replace_more(limit=0)

    top_level_comments = submission.comments[:limit_top_level]
    if not top_level_comments:
        return "   (No comments found)"

    for i, comment in enumerate(top_level_comments, 1):
        try:
            author = comment.author.name if comment.author else "[Deleted]"
            body = comment.body.replace("\n", " ")[:200]
            buffer += f"   [C{i}] {author} (Score: {comment.score}): {body}\n"

            if max_depth >= 1 and len(comment.replies) > 0:
                for reply in comment.replies[:2]:
                    r_author = reply.author.name if reply.author else "[Deleted]"
                    r_body = reply.body.replace("\n", " ")[:150]
                    buffer += f"      └─ {r_author}: {r_body}\n"
        except Exception:
            continue

    return buffer


# ==========================================
# 3) KPI calculation
# ==========================================

def calculate_kpi_metrics(post_iterator, limit: int = 15) -> tuple[int, int]:
    upvotes: list[int] = []
    comments: list[int] = []
    for post in post_iterator:
        if getattr(post, "stickied", False):
            continue
        upvotes.append(int(getattr(post, "score", 0)))
        comments.append(int(getattr(post, "num_comments", 0)))
        if len(upvotes) >= limit:
            break
    if not upvotes:
        return 0, 0
    return int(sum(upvotes) / len(upvotes)), int(sum(comments) / len(comments))


# ==========================================
# 4) Data mining & assembly
# ==========================================

def mine_subreddit_data(sub_list: list[str]) -> str:
    print(f"\nStarting Deep Dive Analysis for {len(sub_list)} subreddits...\n")

    ai_buffer = "Here is the Deep Dive Data (Metrics + Style References) for the selected subreddits:\n\n"
    kpi_export_data: list[dict[str, object]] = []

    for idx, raw_name in enumerate(sub_list, 1):
        sub_name = str(raw_name).strip()
        if not sub_name:
            continue

        print(f"[{idx}/{len(sub_list)}] Mining r/{sub_name}...", end="", flush=True)

        try:
            subreddit = reddit.subreddit(sub_name)

            hot_up, hot_com = calculate_kpi_metrics(subreddit.hot(limit=25))
            week_up, week_com = calculate_kpi_metrics(subreddit.top(time_filter="week", limit=25))
            month_up, month_com = calculate_kpi_metrics(subreddit.top(time_filter="month", limit=25))

            eng_ratio = round(hot_com / hot_up, 3) if hot_up > 0 else 0
            retention_multiplier = round(month_up / hot_up, 1) if hot_up > 0 else 0

            kpi_export_data.append(
                {
                    "Subreddit": sub_name,
                    "Hot_Avg_Upvotes": hot_up,
                    "Hot_Avg_Comments": hot_com,
                    "TopWeek_Avg_Upvotes": week_up,
                    "TopMonth_Avg_Upvotes": month_up,
                    "Engagement_Ratio": eng_ratio,
                }
            )

            ai_buffer += f"### TARGET SUBREDDIT: r/{sub_name}\n"
            ai_buffer += "**PART 1: TRAFFIC & DIFFICULTY METRICS**\n"
            ai_buffer += f"- **Entry Level (Hot)**: Needs ~{hot_up} upvotes & ~{hot_com} comments to trend.\n"

            ai_buffer += f"- **Engagement Style**: Ratio is {eng_ratio}. "
            if eng_ratio > 0.15:
                ai_buffer += "(High Discussion: Users love to argue/comment. Text posts work best.)\n"
            elif eng_ratio < 0.05:
                ai_buffer += "(Lurker Heavy: Users vote but rarely comment. Needs high visual impact/images.)\n"
            else:
                ai_buffer += "(Balanced: Mix of consumption and discussion.)\n"

            ai_buffer += f"- **Viral Ceiling (Top of Month)**: ~{month_up} upvotes.\n"
            ai_buffer += f"- **Difficulty Multiplier**: Top posts are {retention_multiplier}x bigger than Hot posts. "
            if retention_multiplier > 10:
                ai_buffer += "(EXTREME Difficulty: Content dies fast unless it's a masterpiece.)\n"
            else:
                ai_buffer += "(Moderate Stability: Good content stays visible longer.)\n\n"

            ai_buffer += "**PART 2: STYLE REFERENCE (Top 3 Posts from this Month)**\n"
            top_posts = subreddit.top(time_filter="month", limit=10)
            count = 0
            for post in top_posts:
                if getattr(post, "stickied", False):
                    continue
                count += 1
                if count > 3:
                    break

                comment_tree_str = get_comment_tree_text(post, limit_top_level=3, max_depth=1)
                selftext = (post.selftext or "").replace("\n", " ")
                if len(selftext) > 400:
                    selftext = selftext[:400] + "...(truncated)"
                if not selftext:
                    selftext = "[Image/Link Post Only]"

                ai_buffer += f"--- Ref Post #{count} ---\n"
                ai_buffer += f"Title: {post.title}\n"
                ai_buffer += f"Body: {selftext}\n"
                ai_buffer += f"Comments Vibe:\n{comment_tree_str}\n"

            ai_buffer += "=" * 40 + "\n\n"
            print(" OK")

        except Exception as e:
            print(f" Error ({e})")
            ai_buffer += f"### r/{sub_name}: Error scraping data ({e})\n\n"

    if kpi_export_data:
        df = pd.DataFrame(kpi_export_data)
        excel_filename = f"Phase4_KPI_Analysis_{TIMESTAMP}.xlsx"
        df.to_excel(excel_filename, index=False)
        print(f"\nKPI Data saved to: {excel_filename}")

    return ai_buffer


# ==========================================
# 5) Gemini generation
# ==========================================

DEFAULT_PHASE4_PROMPT = """
{{mined_context}}

### TASK: Phase 4 - Content Creation & KPI Strategy

You are the "Reddit Ghostwriter". Above is the REAL data (KPIs + Style References) for our target subreddits.
Your goal is to maximize the probability of our product (from Phase 1 context) trending in these communities.

Requirement 1: The Strategic Analysis Table & Legend
1. The Table: Create a comprehensive Markdown table using the "Traffic & Difficulty Metrics" provided.
   - Columns:
     1. Subreddit
     2. Difficulty Score: (Assess based on the "Viral Ceiling" and "Difficulty Multiplier").
     3. Engagement Type: (Based on the "Engagement Ratio" provided in metrics - e.g., "High Debate", "Visual/Lurker", "Balanced").
     4. Content Strategy Note: CRITICAL. Do NOT give generic advice.
        - If Engagement Type is High Debate -> Suggest a controversial title or a question.
        - If Engagement Type is Visual -> Suggest a UI screenshot or meme format.
        - If Difficulty Multiplier is high -> Emphasize that the content must be "Best of Month" quality to survive.

2. Methodology (The Formulas):
   Immediately following the table, add a compact section titled "KPI Methodology". Display the algorithm formulas used to derive the metrics. Keep explanations strictly concise and academic.
   Format Requirements:
   - Engagement Index ($E$): Formula: `Avg. Comments / Avg. Upvotes`. *Indicates community interaction depth.*
   - Viral Ceiling ($V$): Formula: `Top(Month)_avg / Hot_avg`. *Measures the volatility barrier for long-term retention.*

Requirement 2: Native Content Drafting (The Core)
For EACH of the target subreddits, write a tailored draft.
- Format: Determine if it should be a Text Post or a Link/Image Post based on the reference data.
- Title: Must be click-worthy but NOT clickbait. Use the linguistic style of that sub (e.g., lowercase for tech subs, formal for academic subs).
- Body: Write the full post body. Do not be salesy. Use the "Trojan Horse" technique: provide 80% value/story/insight, and mention the product only as a natural part of the solution (20%).
- Seeding Comments: Write 3-5 distinct comments that we can use to "seed" the discussion. These should look like genuine user questions or reactions (e.g., "Skeptical but interested", "Asking about privacy", "Joke about the problem").
  - Format: Display these as a simulated comment tree (e.g., User A asks -> User B answers).

Output Format:
Please structure the response clearly with Markdown headers for each Subreddit.
"""


def run_phase4_generation(*, history_path: Path, history: list[dict[str, object]], context_data: str) -> str:
    print("\nSending mined data to Gemini for Final Content Drafting...")

    template = PROMPTS.get("phase4_prompt", DEFAULT_PHASE4_PROMPT)
    phase4_prompt = render_prompt(template, mined_context=context_data)

    chat = client.chats.create(model=MODEL_ID, history=history)
    response = chat.send_message(
        phase4_prompt,
        config={
            "temperature": 0.3,
            "max_output_tokens": 20000,
        },
    )

    full_response = response.text or ""

    append_message(history_path, role="user", text=phase4_prompt)
    append_message(history_path, role="model", text=full_response)

    return full_response


def main() -> int:
    run_dir = Path.cwd()
    history_path = get_history_path(run_dir)
    history = load_history(history_path)
    if not history:
        print(f"Error: missing chat history at '{history_path}'. Run workflow1.py and workflow2.py first.")
        return 1

    context_buffer = mine_subreddit_data([str(s) for s in target_subreddits])
    full_response = run_phase4_generation(history_path=history_path, history=history, context_data=context_buffer)

    final_filename = f"project_final_content_plan_{TIMESTAMP}.md"
    Path(final_filename).write_text(full_response + "\n", encoding="utf-8")

    print("\n" + "=" * 50)
    print("WORKFLOW COMPLETE!")
    print(f"Final Report: '{final_filename}'")
    print("=" * 50)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

