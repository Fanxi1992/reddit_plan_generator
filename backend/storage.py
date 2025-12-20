from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import RUNS_DIR

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(
            "Invalid run_id. Use only letters/digits/underscore/dash, start with a letter/digit, max 64 chars."
        )


def get_run_dir(run_id: str) -> Path:
    validate_run_id(run_id)
    return RUNS_DIR / run_id


def ensure_runs_dir() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def get_latest_file(run_dir: Path, pattern: str) -> Path | None:
    matches = list(run_dir.glob(pattern))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def find_key_outputs(run_dir: Path) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    part1 = get_latest_file(run_dir, "project_part1_positioning_*.md")
    part2 = get_latest_file(run_dir, "project_part2_strategy_*.md")
    final = get_latest_file(run_dir, "project_final_content_plan_*.md")

    if part1:
        outputs["part1"] = part1
    if part2:
        outputs["part2"] = part2
    if final:
        outputs["final"] = final

    return outputs


def read_json_if_exists(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

