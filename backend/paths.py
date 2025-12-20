from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

RUNS_DIR = REPO_ROOT / "runs"
PROMPTS_DIR = REPO_ROOT / "prompts"
DEFAULT_PROMPTS_PATH = PROMPTS_DIR / "default_prompts.json"

WORKFLOW_SCRIPTS = [
    REPO_ROOT / "workflow1.py",
    REPO_ROOT / "workflow2.py",
    REPO_ROOT / "workflow3.py",
    REPO_ROOT / "workflow4.py",
]

