
import os
import json
import re
from google import genai

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------
# API_KEY = os.environ.get("GOOGLE_API_KEY", "YOUR_API_KEY_HERE")
MODEL_ID = "gemini-3-flash-preview"

# Load the session ID from Phase 1
try:
    with open("session_id.txt", "r") as f:
        SESSION_ID = f.read().strip()
    print(f"📂 Loaded Session ID: {SESSION_ID}")
except FileNotFoundError:
    print("❌ Error: 'session_id.txt' not found. Please run Phase 1 first.")
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
    # Resume the session using previous_interaction_id
    interaction = client.interactions.create(
    model=MODEL_ID,
    previous_interaction_id=SESSION_ID,
    input=PHASE2_PROMPT,
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
        
        # Save JSON for the PRAW script (Phase 3)
        with open("raw_subreddits.json", "w") as f:
            json.dump(subreddit_list, f, indent=4)
        print(f"\n📦 [File Created] 'raw_subreddits.json' containing {len(subreddit_list)} subs.")
        print(f"   Sample: {subreddit_list[:5]}...")
    else:
        print("\n⚠️ Warning: Could not auto-extract JSON. Saving full text only.")

    # 2. Save the Report Text (Positioning)
    # We remove the JSON part from the report to make it clean
    report_text = re.sub(r"```json\s*\[.*?\]\s*```", "", full_response, flags=re.DOTALL).strip()

    with open("project_part1_positioning.md", "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"📄 [File Created] 'project_part1_positioning.md' (The Marketing Report).")

    # Update Session ID (Just in case ID rotates, though usually it stays same for the thread)
    with open("session_id.txt", "w") as f:
        f.write(interaction.id)



except Exception as e:
    print(f"\n❌ Error: {e}")
