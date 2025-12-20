import os
import json
import datetime
from google import genai

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------
# API_KEY = os.environ.get("GOOGLE_API_KEY", "YOUR_API_KEY_HERE")
MODEL_ID = "gemini-3-pro-preview"

# [MODIFIED] 生成当前运行的时间戳
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

client = genai.Client()

# -------------------------------------------------------------------------
# Prompt & Context (All English to avoid UTF-8 bugs)
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
        with open(prompts_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
    except Exception as e:
        print(f"?? Warning: Failed to load PROMPTS_FILE='{prompts_file}': {e}")
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
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read().strip()
    return default_text.strip()


PRODUCT_CONTEXT = load_product_context(DEFAULT_PRODUCT_CONTEXT)
PROMPTS = load_prompts()

# Assemble the input (support per-run override via PROMPTS_FILE)
phase1_template = PROMPTS.get("phase1_prompt", DEFAULT_PHASE1_PROMPT)
initial_input = render_prompt(phase1_template, product_context=PRODUCT_CONTEXT)

# -------------------------------------------------------------------------
# Execution
# -------------------------------------------------------------------------
print("🚀 Connecting to Gemini Interactions API (English Mode)...")

try:
    # Single call should be safe now that we are using English
    interaction = client.interactions.create(
        model=MODEL_ID,
        input=initial_input,
    )

    print("\n" + "="*50)
    print("✅ Phase 1 Success: Session Created")
    print(f"🔗 Interaction ID: {interaction.id}")
    print("="*50)
    
    print("\n🤖 AI Response:")
    print(interaction.outputs[-1].text)

    # [MODIFIED] Save Session ID specifically for Phase 1 with Timestamp
    session_filename = f"session_id_phase1_{TIMESTAMP}.txt"
    with open(session_filename, "w") as f:
        f.write(interaction.id)
    print(f"\n[Info] Session ID saved to '{session_filename}'. Ready for Phase 2.")

except Exception as e:
    print(f"\n❌ Error: {e}")
