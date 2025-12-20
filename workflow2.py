import os
import json
import re
import glob
import datetime
from google import genai

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------
MODEL_ID = "gemini-3-pro-preview"
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def load_prompts() -> dict[str, str]:
    """Load per-run prompts from PROMPTS_FILE (JSON), if provided."""
    prompts_file = os.environ.get("PROMPTS_FILE")
    if not prompts_file:
        return {}

    try:
        with open(prompts_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
    except Exception as e:
        print(f"?? Warning: Failed to load PROMPTS_FILE='{prompts_file}': {e}")
        return {}


PROMPTS = load_prompts()

# [MODIFIED] Helper function to find the latest file matching a pattern
def get_latest_file(pattern):
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getctime)

# [MODIFIED] Load the LATEST Phase 1 Session ID
latest_session_file = get_latest_file("session_id_phase1_*.txt")

try:
    if not latest_session_file:
        raise FileNotFoundError("No 'session_id_phase1_*.txt' found.")
    
    with open(latest_session_file, "r") as f:
        SESSION_ID = f.read().strip()
    print(f"📂 Loaded Session ID from: {latest_session_file}")
    print(f"🔗 ID: {SESSION_ID}")
except Exception as e:
    print(f"❌ Error loading session: {e}")
    exit()

client = genai.Client()

# -------------------------------------------------------------------------
# Prompt for Phase 2: Positioning Report + JSON List
# -------------------------------------------------------------------------

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

# -------------------------------------------------------------------------

# Execution

# -------------------------------------------------------------------------

print("🚀 Sending Phase 2 instructions (Positioning + List Gen)...")

try:
    phase2_prompt = PROMPTS.get("phase2_prompt", PHASE2_PROMPT)

    # Resume the session using previous_interaction_id
    interaction = client.interactions.create(
    model=MODEL_ID,
    previous_interaction_id=SESSION_ID,
    input=phase2_prompt,
    )


    full_response = interaction.outputs[-1].text

    print("\n" + "="*50)
    print("✅ Phase 2 Complete. Processing outputs...")
    print("="*50)

    # -------------------------------------------------------------------------
    # Output Handling: Split Text and JSON
    # -------------------------------------------------------------------------

    # 1. Extract JSON Block using Regex
    json_match = re.search(r"```json\s*(\[.*?\])\s*```", full_response, re.DOTALL)

    if json_match:
        json_str = json_match.group(1)
        subreddit_list = json.loads(json_str)
        
        # [MODIFIED] Save JSON with Timestamp
        json_filename = f"raw_subreddits_{TIMESTAMP}.json"
        with open(json_filename, "w") as f:
            json.dump(subreddit_list, f, indent=4)
        print(f"\n📦 [File Created] '{json_filename}' containing {len(subreddit_list)} subs.")
    else:
        print("\n⚠️ Warning: Could not auto-extract JSON. Saving full text only.")

    # 2. Save the Report Text (Positioning)
    # We remove the JSON part from the report to make it clean
    report_text = re.sub(r"```json\s*\[.*?\]\s*```", "", full_response, flags=re.DOTALL).strip()
    # [MODIFIED] Save Markdown with Timestamp
    report_filename = f"project_part1_positioning_{TIMESTAMP}.md"
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"📄 [File Created] '{report_filename}'.")

    # [MODIFIED] Save Updated Session ID for Phase 2
    new_session_filename = f"session_id_phase2_{TIMESTAMP}.txt"
    with open(new_session_filename, "w") as f:
        f.write(interaction.id)
    print(f"🔗 [Session Updated] Saved to '{new_session_filename}'")



except Exception as e:
    print(f"\n❌ Error: {e}")
