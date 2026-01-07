from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

RUNS_DIR = REPO_ROOT / "runs"
PROMPTS_DIR = REPO_ROOT / "prompts"
DEFAULT_PROMPTS_PATH = PROMPTS_DIR / "default_prompts.json"

WORKFLOW_SCRIPTS = [
    REPO_ROOT / "paid_workflow1_scrape.py",
    REPO_ROOT / "paid_workflow2_dossier.py",
    REPO_ROOT / "paid_workflow3_post_v1.py",
    REPO_ROOT / "paid_workflow4_mod_review.py",
    REPO_ROOT / "paid_workflow5_post_v2.py",
    REPO_ROOT / "paid_workflow6_post_final.py",
    REPO_ROOT / "paid_workflow7_engagement_kit.py",
]

