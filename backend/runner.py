from __future__ import annotations

import datetime
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from google import genai

from .chat_history import append_message, get_history_path
from .paths import WORKFLOW_SCRIPTS
from .prompts import load_default_prompts, merge_prompts, write_prompts_file
from .strategies import validate_strategy_id
from .storage import ensure_runs_dir, find_key_outputs, get_run_dir, read_json_if_exists, validate_run_id


class RunAlreadyRunningError(RuntimeError):
    pass


class RunNotFoundError(RuntimeError):
    pass


class RunCancelledError(RuntimeError):
    pass


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


STATE_FILENAME = "run_state.json"


@dataclass
class RunRecord:
    run_id: str
    run_dir: Path
    status: RunStatus = RunStatus.PENDING
    current_phase: str | None = None
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None
    error: str | None = None
    outputs: dict[str, Path] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "current_phase": self.current_phase,
            "run_dir": str(self.run_dir),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
            "outputs": {k: v.name for k, v in self.outputs.items()},
        }

    def persist(self) -> None:
        tmp_path = self.run_dir / f".{STATE_FILENAME}.tmp"
        final_path = self.run_dir / STATE_FILENAME
        tmp_path.write_text(
            json_dumps_pretty(self.to_dict()),
            encoding="utf-8",
        )
        tmp_path.replace(final_path)


def json_dumps_pretty(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


def terminate_process(process: subprocess.Popen, *, timeout_sec: float = 5.0) -> None:
    try:
        process.terminate()
    except Exception:
        return

    try:
        process.wait(timeout=timeout_sec)
    except Exception:
        pass

    try:
        process.kill()
    except Exception:
        return

    try:
        process.wait(timeout=timeout_sec)
    except Exception:
        return


class RunControl:
    def __init__(self) -> None:
        self.cancel_event = threading.Event()
        self.process_lock = threading.Lock()
        self.process: subprocess.Popen | None = None


def _parse_max_concurrent_runs() -> int:
    raw = (os.environ.get("MAX_CONCURRENT_RUNS") or "").strip()
    if not raw:
        return 1
    try:
        value = int(raw)
    except Exception:
        return 1
    return max(1, value)


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Default: preserve the existing "only one run at a time" behavior.
        # Set MAX_CONCURRENT_RUNS>1 to allow parallel runs.
        self._execution_lock = threading.BoundedSemaphore(_parse_max_concurrent_runs())
        self._runs: dict[str, RunRecord] = {}
        self._controls: dict[str, RunControl] = {}

    @staticmethod
    def _normalize_subreddit_for_run_id(target_subreddit: str) -> str:
        """
        Normalize a subreddit name to a filesystem- and run_id-safe suffix.
        Keeps only [A-Za-z0-9_-], trims separators, lowercases, and caps length.
        """
        raw = (target_subreddit or "").strip()
        if raw.lower().startswith("r/"):
            raw = raw[2:]
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-_").lower()
        # Keep run_id <= 64 chars; timestamp is 15 chars, plus "_" => max 48.
        return safe[:48]

    @classmethod
    def _build_default_run_id(cls, *, target_subreddit: str) -> str:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = cls._normalize_subreddit_for_run_id(target_subreddit)
        return f"{timestamp}_{suffix}" if suffix else timestamp

    def start_run(
        self,
        *,
        target_subreddit: str,
        pre_materials: str,
        brief_mode: str,
        options: dict | None,
        prompt_overrides: dict[str, str] | None,
        strategy_id: str | None,
        strategy_notes: str | None,
        post_v1_mode: str,
        post_v1_client_draft: str | None,
        stop_after_mod_review: bool,
        run_id: str | None,
        wait: bool,
    ) -> RunRecord:
        ensure_runs_dir()

        base_run_id = run_id or self._build_default_run_id(target_subreddit=target_subreddit)
        validate_run_id(base_run_id)

        brief_mode_norm = (brief_mode or "extract").strip().lower()
        if brief_mode_norm not in {"extract", "raw"}:
            brief_mode_norm = "extract"

        if not self._execution_lock.acquire(blocking=False):
            raise RunAlreadyRunningError("A run is already in progress.")

        record: RunRecord | None = None

        try:
            def allocate_run_dir(run_id_base: str) -> tuple[str, Path]:
                # When run_id is auto-generated, concurrent starts might collide (same second).
                # We retry with a short random suffix to ensure a unique directory.
                allow_suffix = run_id is None
                attempts = 6 if allow_suffix else 1
                last_error: Exception | None = None
                for attempt in range(attempts):
                    if attempt == 0:
                        candidate_id = run_id_base
                    else:
                        suffix = secrets.token_hex(3)  # 6 chars, [0-9a-f]
                        max_base = 64 - (1 + len(suffix))
                        trimmed = run_id_base[:max_base].rstrip("-_") or run_id_base[:max_base]
                        candidate_id = f"{trimmed}_{suffix}"
                    validate_run_id(candidate_id)
                    candidate_dir = get_run_dir(candidate_id)
                    try:
                        candidate_dir.mkdir(parents=True, exist_ok=False)
                        return candidate_id, candidate_dir
                    except FileExistsError as e:
                        last_error = e
                        if not allow_suffix:
                            raise
                        continue
                raise last_error or FileExistsError("Failed to allocate a unique run directory.")

            final_run_id, run_dir = allocate_run_dir(base_run_id)

            record = RunRecord(run_id=final_run_id, run_dir=run_dir)
            record.persist()

            with self._lock:
                self._runs[final_run_id] = record
                self._controls[final_run_id] = RunControl()

            default_prompts = load_default_prompts()
            skip_keys = {"brief_prompt"} if brief_mode_norm == "raw" else None
            prompts = merge_prompts(default_prompts, prompt_overrides, skip_keys=skip_keys)

            if wait:
                self._run(
                    record,
                    target_subreddit=target_subreddit,
                    pre_materials=pre_materials,
                    brief_mode=brief_mode_norm,
                    options=options or {},
                    prompts=prompts,
                    strategy_id=strategy_id,
                    strategy_notes=strategy_notes,
                    post_v1_mode=post_v1_mode,
                    post_v1_client_draft=post_v1_client_draft,
                    stop_after_mod_review=stop_after_mod_review,
                )
            else:
                thread = threading.Thread(
                    target=self._run,
                    kwargs={
                        "record": record,
                        "target_subreddit": target_subreddit,
                        "pre_materials": pre_materials,
                        "brief_mode": brief_mode_norm,
                        "options": options or {},
                        "prompts": prompts,
                        "strategy_id": strategy_id,
                        "strategy_notes": strategy_notes,
                        "post_v1_mode": post_v1_mode,
                        "post_v1_client_draft": post_v1_client_draft,
                        "stop_after_mod_review": stop_after_mod_review,
                    },
                    daemon=True,
                )
                thread.start()

            return record

        except Exception as e:
            # If we fail before `_run()` starts, we must release the execution lock
            # to avoid permanently blocking future runs.
            if record is not None:
                record.status = RunStatus.FAILED
                record.error = str(e)
                record.finished_at = datetime.datetime.now(datetime.UTC)
                try:
                    record.persist()
                except Exception:
                    pass

            self._execution_lock.release()
            raise

    def cancel_run(self, run_id: str) -> RunRecord:
        validate_run_id(run_id)

        record = self.get_run(run_id)
        if not record:
            raise RunNotFoundError("Run not found.")

        with self._lock:
            live_record = self._runs.get(run_id)
            control = self._controls.get(run_id)

        if live_record and live_record.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
            return live_record

        if record.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
            return record

        if control:
            control.cancel_event.set()
            with control.process_lock:
                process = control.process
            if process and process.poll() is None:
                terminate_process(process)

        target = live_record or record
        target.status = RunStatus.CANCELLED
        target.error = "Cancelled by user."
        target.finished_at = datetime.datetime.now(datetime.UTC)
        try:
            target.persist()
        except Exception:
            pass

        return target

    def get_run(self, run_id: str) -> RunRecord | None:
        validate_run_id(run_id)

        with self._lock:
            record = self._runs.get(run_id)
            if record:
                return record

        run_dir = get_run_dir(run_id)
        state = read_json_if_exists(run_dir / STATE_FILENAME)
        if not state:
            return None

        def parse_dt(value: str | None) -> datetime.datetime | None:
            if not value:
                return None
            try:
                return datetime.datetime.fromisoformat(value)
            except Exception:
                return None

        try:
            status = RunStatus(state.get("status", "unknown"))
        except Exception:
            status = RunStatus.UNKNOWN

        outputs: dict[str, Path] = {}
        raw_outputs = state.get("outputs")
        if isinstance(raw_outputs, dict):
            for key, filename in raw_outputs.items():
                if isinstance(key, str) and isinstance(filename, str):
                    candidate = run_dir / filename
                    if candidate.is_file():
                        outputs[key] = candidate

        record = RunRecord(
            run_id=run_id,
            run_dir=run_dir,
            status=status,
            current_phase=state.get("current_phase"),
            created_at=parse_dt(state.get("created_at")) or datetime.datetime.now(datetime.UTC),
            started_at=parse_dt(state.get("started_at")),
            finished_at=parse_dt(state.get("finished_at")),
            error=state.get("error"),
            outputs=outputs,
        )
        return record

    def _run(
        self,
        record: RunRecord,
        *,
        target_subreddit: str,
        pre_materials: str,
        brief_mode: str,
        options: dict,
        prompts: dict[str, str],
        strategy_id: str | None,
        strategy_notes: str | None,
        post_v1_mode: str,
        post_v1_client_draft: str | None,
        stop_after_mod_review: bool,
    ) -> None:
        now_local = datetime.datetime.now().astimezone()
        current_date = now_local.date().isoformat()
        current_datetime = now_local.isoformat(timespec="seconds")

        client_post_draft_filename = "client_post_draft.md"
        post_v1_mode_norm = (post_v1_mode or "generate").strip().lower()
        if post_v1_mode_norm not in {"generate", "client_draft"}:
            post_v1_mode_norm = "generate"

        strategy_id_norm = (strategy_id or "").strip() or "free"
        try:
            validate_strategy_id(strategy_id_norm)
        except Exception:
            strategy_id_norm = "free"
        strategy_notes_norm = (strategy_notes or "").strip() or None

        brief_mode_norm = (brief_mode or "extract").strip().lower()
        if brief_mode_norm not in {"extract", "raw"}:
            brief_mode_norm = "extract"

        config_path = record.run_dir / "run_config.json"
        pre_materials_path = record.run_dir / "pre_materials.md"
        brief_md_path = record.run_dir / "product_brief.md"
        brief_json_path = record.run_dir / "product_brief.json"
        prompts_path = record.run_dir / "prompts.json"
        log_path = record.run_dir / "run.log"

        try:
            with self._lock:
                control = self._controls.get(record.run_id)

            if control and control.cancel_event.is_set():
                raise RunCancelledError()

            record.status = RunStatus.RUNNING
            record.started_at = datetime.datetime.now(datetime.UTC)
            record.persist()

            config: dict[str, object] = {
                "target_subreddit": target_subreddit,
                "options": options,
                "current_date": current_date,
                "current_datetime": current_datetime,
                "brief_mode": brief_mode_norm,
                "strategy_id": strategy_id_norm,
                "strategy_notes": strategy_notes_norm,
                "post_v1_mode": post_v1_mode_norm,
                "stop_after_mod_review": bool(stop_after_mod_review),
            }
            if post_v1_mode_norm == "client_draft":
                if not (post_v1_client_draft or "").strip():
                    raise ValueError("post_v1_client_draft is required when post_v1_mode is 'client_draft'.")
                config["client_post_draft_filename"] = client_post_draft_filename
                (record.run_dir / client_post_draft_filename).write_text(
                    post_v1_client_draft or "",
                    encoding="utf-8",
                )

            config_path.write_text(
                json_dumps_pretty(config)
                + "\n",
                encoding="utf-8",
            )
            write_prompts_file(prompts_path, prompts)

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            # Force UTF-8 for redirected stdout/stderr (Windows locale might be GBK which can't encode emojis).
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["PROMPTS_FILE"] = str(prompts_path)
            env["RUN_CONFIG_FILE"] = str(config_path)

            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"[config] strategy_id={strategy_id_norm}\n")
                if strategy_notes_norm:
                    log_file.write("[config] strategy_notes provided\n")
                log_file.flush()
                if post_v1_mode_norm == "client_draft":
                    log_file.write(
                        f"[config] post_v1_mode=client_draft; saved {client_post_draft_filename} for stage post_v1\n"
                    )
                    log_file.flush()
                log_file.write(f"[config] brief_mode={brief_mode_norm}\n")
                log_file.flush()
                if stop_after_mod_review:
                    log_file.write(
                        "[config] stop_after_mod_review=true; workflow will stop after paid_workflow4_mod_review.py\n"
                    )
                    log_file.flush()
                # ------------------------------------------------------------
                # Stage 0: Persist pre-materials + extract product brief
                # ------------------------------------------------------------
                if control and control.cancel_event.is_set():
                    raise RunCancelledError()

                record.current_phase = "stage0_brief"
                record.persist()
                log_file.write("[stage0_brief] Saving pre-materials and extracting product brief\n")
                log_file.flush()

                # Persist the raw pre-materials for later reuse/review.
                # Note: we still keep the extracted Product Brief as the ONLY chat context for this run.
                raw_pre_materials = pre_materials
                if not raw_pre_materials.endswith("\n"):
                    raw_pre_materials += "\n"
                pre_materials_path.write_text(raw_pre_materials, encoding="utf-8")

                if brief_mode_norm == "raw":
                    brief_md = (pre_materials or "").strip()
                    if brief_md:
                        brief_md_path.write_text(brief_md + "\n", encoding="utf-8")

                    history_path = get_history_path(record.run_dir)
                    append_message(
                        history_path,
                        role="user",
                        text=(
                            "Context note: upfront pre-materials are provided verbatim below as the Product Brief for this run (no summarization). "
                            "Treat it as the ONLY authoritative context for this run.\n\n"
                            f"Target Subreddit: r/{target_subreddit.strip()}\n\n"
                            f"{brief_md}"
                        ),
                    )

                    log_file.write("[stage0_brief] Saved product_brief.md (raw) and seeded chat history\n")
                    log_file.flush()
                else:
                    brief_text = generate_product_brief(prompts["brief_prompt"], pre_materials=pre_materials)
                    brief_json = extract_json_object(brief_text)
                    brief_md = strip_json_code_blocks(brief_text).strip()
                    if not brief_md:
                        brief_md = (brief_text or "").strip()
                    if brief_md:
                        brief_md_path.write_text(brief_md + "\n", encoding="utf-8")
                    if brief_json is not None:
                        brief_json_path.write_text(json_dumps_pretty(brief_json) + "\n", encoding="utf-8")

                    # Seed chat history with the extracted brief so subsequent stages and /chat share context.
                    history_path = get_history_path(record.run_dir)
                    append_message(
                        history_path,
                        role="user",
                        text=(
                            "Context note: upfront pre-materials were provided out-of-band and are not included in chat context. "
                            "Use ONLY the following extracted Product Brief as authoritative context for this run.\n\n"
                            f"Target Subreddit: r/{target_subreddit.strip()}\n\n"
                            f"{brief_md}"
                        ),
                    )

                    log_file.write("[stage0_brief] Saved product_brief.md/product_brief.json and seeded chat history\n")
                    log_file.flush()

                scripts_to_run = WORKFLOW_SCRIPTS
                if stop_after_mod_review:
                    stop_at = "paid_workflow4_mod_review.py"
                    stop_index = next(
                        (idx for idx, script in enumerate(WORKFLOW_SCRIPTS) if script.name == stop_at),
                        None,
                    )
                    if stop_index is None:
                        raise RuntimeError(f"{stop_at} not found in WORKFLOW_SCRIPTS")
                    scripts_to_run = WORKFLOW_SCRIPTS[: stop_index + 1]

                for script_path in scripts_to_run:
                    if control and control.cancel_event.is_set():
                        raise RunCancelledError()

                    record.current_phase = script_path.name
                    record.persist()

                    process = subprocess.Popen(
                        # `-X utf8` ensures the child process uses UTF-8 even when stdout is redirected to a file.
                        [sys.executable, "-X", "utf8", str(script_path)],
                        cwd=str(record.run_dir),
                        env=env,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                    )

                    if control:
                        with control.process_lock:
                            control.process = process

                    try:
                        while True:
                            if control and control.cancel_event.is_set():
                                terminate_process(process)
                                raise RunCancelledError()

                            ret = process.poll()
                            if ret is not None:
                                if ret != 0:
                                    raise subprocess.CalledProcessError(ret, process.args)
                                break

                            time.sleep(0.25)
                    finally:
                        if control:
                            with control.process_lock:
                                if control.process is process:
                                    control.process = None

            if control and control.cancel_event.is_set():
                raise RunCancelledError()

            record.outputs = find_key_outputs(record.run_dir)
            record.status = RunStatus.SUCCEEDED
            record.finished_at = datetime.datetime.now(datetime.UTC)
            record.persist()

        except RunCancelledError:
            record.status = RunStatus.CANCELLED
            record.error = "Cancelled by user."
            record.finished_at = datetime.datetime.now(datetime.UTC)
            try:
                record.persist()
            except Exception:
                pass
        except subprocess.CalledProcessError as e:
            if control and control.cancel_event.is_set():
                record.status = RunStatus.CANCELLED
                record.error = "Cancelled by user."
            else:
                record.status = RunStatus.FAILED
                record.error = f"{record.current_phase} failed with exit code {e.returncode}"
            record.finished_at = datetime.datetime.now(datetime.UTC)
            try:
                record.persist()
            except Exception:
                pass
        except Exception as e:
            if control and control.cancel_event.is_set():
                record.status = RunStatus.CANCELLED
                record.error = "Cancelled by user."
            else:
                record.status = RunStatus.FAILED
                record.error = str(e)
            record.finished_at = datetime.datetime.now(datetime.UTC)
            try:
                record.persist()
            except Exception:
                pass
        finally:
            if control:
                with control.process_lock:
                    control.process = None
            self._execution_lock.release()


def strip_json_code_blocks(text: str) -> str:
    return re.sub(r"```json\s*\{.*?\}\s*```", "", text, flags=re.DOTALL)


def extract_json_object(text: str) -> dict | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if not match:
        return None
    import json

    try:
        obj = json.loads(match.group(1))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def generate_product_brief(template: str, *, pre_materials: str) -> str:
    model_id = os.environ.get("GEMINI_MODEL", "gemini-3-pro-preview")
    prompt = template.replace("{{pre_materials}}", pre_materials.strip())

    client = genai.Client()
    chat = client.chats.create(model=model_id, history=[])
    response = chat.send_message(
        prompt,
        config={
            "temperature": 0.2,
            "max_output_tokens": 4096,
        },
    )
    return response.text or ""
