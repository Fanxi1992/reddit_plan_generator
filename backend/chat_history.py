from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HISTORY_FILENAME = "chat_history.jsonl"


def get_history_path(run_dir: Path) -> Path:
    return run_dir / HISTORY_FILENAME


def load_history(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []

    history: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in history file {path} at line {line_no}: {e}") from e

        role = obj.get("role")
        parts = obj.get("parts")
        if role not in ("user", "model"):
            raise ValueError(
                f"Invalid history message role in {path} at line {line_no}: expected 'user' or 'model', got {role!r}"
            )
        if not isinstance(parts, list) or not parts:
            raise ValueError(f"Invalid history message parts in {path} at line {line_no}: expected non-empty list")
        first = parts[0]
        if not isinstance(first, dict) or not isinstance(first.get("text"), str):
            raise ValueError(
                f"Invalid history message parts[0].text in {path} at line {line_no}: expected string"
            )

        history.append({"role": role, "parts": [{"text": first["text"]}]})

    return history


def append_message(path: Path, *, role: str, text: str) -> None:
    if role not in ("user", "model"):
        raise ValueError(f"Invalid role: {role!r}")
    record = {"role": role, "parts": [{"text": text}]}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

