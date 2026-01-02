from __future__ import annotations

import datetime
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .paths import WORKFLOW_SCRIPTS
from .prompts import load_default_prompts, merge_prompts, write_prompts_file
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


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._execution_lock = threading.Lock()
        self._runs: dict[str, RunRecord] = {}
        self._controls: dict[str, RunControl] = {}

    def start_run(
        self,
        *,
        product_context_md: str,
        prompt_overrides: dict[str, str] | None,
        run_id: str | None,
        wait: bool,
    ) -> RunRecord:
        ensure_runs_dir()

        final_run_id = run_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        validate_run_id(final_run_id)

        if not self._execution_lock.acquire(blocking=False):
            raise RunAlreadyRunningError("A run is already in progress.")

        record: RunRecord | None = None

        try:
            run_dir = get_run_dir(final_run_id)
            run_dir.mkdir(parents=True, exist_ok=False)

            record = RunRecord(run_id=final_run_id, run_dir=run_dir)
            record.persist()

            with self._lock:
                self._runs[final_run_id] = record
                self._controls[final_run_id] = RunControl()

            default_prompts = load_default_prompts()
            prompts = merge_prompts(default_prompts, prompt_overrides)

            if wait:
                self._run(record, product_context_md=product_context_md, prompts=prompts)
            else:
                thread = threading.Thread(
                    target=self._run,
                    kwargs={"record": record, "product_context_md": product_context_md, "prompts": prompts},
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

    def _run(self, record: RunRecord, *, product_context_md: str, prompts: dict[str, str]) -> None:
        product_path = record.run_dir / "product_context.md"
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

            product_path.write_text(product_context_md.strip() + "\n", encoding="utf-8")
            write_prompts_file(prompts_path, prompts)

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            # Force UTF-8 for redirected stdout/stderr (Windows locale might be GBK which can't encode emojis).
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["PRODUCT_CONTEXT_FILE"] = str(product_path)
            env["PROMPTS_FILE"] = str(prompts_path)

            with log_path.open("a", encoding="utf-8") as log_file:
                for script_path in WORKFLOW_SCRIPTS:
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
