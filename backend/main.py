from __future__ import annotations

import os
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from google import genai

from .chat_history import HISTORY_FILENAME, append_message, get_history_path, load_history, load_history_messages
from .prompts import load_default_prompts
from .runner import RunAlreadyRunningError, RunManager, RunNotFoundError, RunStatus
from .schemas import (
    ChatHistoryResponse,
    ChatSendRequest,
    ChatSendResponse,
    PromptsResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunStatusResponse,
 )
from .storage import find_key_outputs, get_run_dir, validate_run_id

app = FastAPI(title="Reddit Workflow Backend", version="0.1.0")

cors_origins = os.getenv("CORS_ORIGINS")
origins = [o.strip() for o in cors_origins.split(",") if o.strip()] if cors_origins else [
    "http://localhost:5173",
    "http://localhost:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RUNS = RunManager()
GENAI = genai.Client()

_chat_locks: dict[str, threading.Lock] = {}
_chat_locks_lock = threading.Lock()


def _get_chat_lock(run_id: str) -> threading.Lock:
    with _chat_locks_lock:
        lock = _chat_locks.get(run_id)
        if lock is None:
            lock = threading.Lock()
            _chat_locks[run_id] = lock
        return lock


def _ensure_run_not_active(run_id: str) -> None:
    record = RUNS.get_run(run_id)
    if record and record.status in (RunStatus.PENDING, RunStatus.RUNNING):
        raise HTTPException(status_code=409, detail="Run is still in progress.")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/prompts", response_model=PromptsResponse)
def get_prompts():
    return PromptsResponse(prompts=load_default_prompts())


@app.post("/api/runs", response_model=RunCreateResponse)
def create_run(payload: RunCreateRequest):
    try:
        options = payload.options.model_dump() if hasattr(payload.options, "model_dump") else payload.options.dict()
        record = RUNS.start_run(
            target_subreddit=payload.target_subreddit,
            pre_materials=payload.pre_materials,
            options=options,
            prompt_overrides=payload.prompt_overrides,
            post_v1_mode=payload.post_v1_mode,
            post_v1_client_draft=payload.post_v1_client_draft,
            stop_after_mod_review=payload.stop_after_mod_review,
            run_id=payload.run_id,
            wait=payload.wait,
        )
    except RunAlreadyRunningError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    downloads: dict[str, str] = {}
    if payload.wait and record.status == RunStatus.SUCCEEDED:
        outputs = record.outputs or find_key_outputs(get_run_dir(record.run_id))
        downloads = {k: f"/api/runs/{record.run_id}/download/{k}" for k in outputs.keys()}

    return RunCreateResponse(
        run_id=record.run_id,
        status=record.status.value,
        downloads=downloads,
        error=record.error,
    )


@app.get("/api/runs/{run_id}", response_model=RunStatusResponse)
def get_run(run_id: str):
    validate_run_id(run_id)

    record = RUNS.get_run(run_id)
    run_dir = get_run_dir(run_id)

    if not record:
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail="Run not found.")
        status = RunStatus.UNKNOWN
        outputs = find_key_outputs(run_dir)
        outputs_names = {k: v.name for k, v in outputs.items()}
        downloads = {key: f"/api/runs/{run_id}/download/{key}" for key in outputs.keys()}

        history_path = run_dir / HISTORY_FILENAME
        if history_path.is_file():
            outputs_names["history"] = history_path.name
            downloads["history"] = f"/api/runs/{run_id}/download/history"
        return RunStatusResponse(
            run_id=run_id,
            status=status.value,
            run_dir=str(run_dir),
            outputs=outputs_names,
            downloads=downloads,
        )

    outputs = record.outputs or find_key_outputs(run_dir)
    outputs_names = {k: v.name for k, v in outputs.items()}
    downloads = {k: f"/api/runs/{run_id}/download/{k}" for k in outputs.keys()}

    history_path = run_dir / HISTORY_FILENAME
    if history_path.is_file():
        outputs_names["history"] = history_path.name
        downloads["history"] = f"/api/runs/{run_id}/download/history"

    return RunStatusResponse(
        run_id=record.run_id,
        status=record.status.value,
        current_phase=record.current_phase,
        run_dir=str(record.run_dir),
        created_at=record.created_at.isoformat() if record.created_at else None,
        started_at=record.started_at.isoformat() if record.started_at else None,
        finished_at=record.finished_at.isoformat() if record.finished_at else None,
        error=record.error,
        outputs=outputs_names,
        downloads=downloads,
    )


@app.post("/api/runs/{run_id}/cancel", response_model=RunStatusResponse)
def cancel_run(run_id: str):
    validate_run_id(run_id)

    try:
        record = RUNS.cancel_run(run_id)
    except RunNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    run_dir = get_run_dir(run_id)
    outputs = record.outputs or find_key_outputs(run_dir)
    outputs_names = {k: v.name for k, v in outputs.items()}
    downloads = {k: f"/api/runs/{run_id}/download/{k}" for k in outputs.keys()}

    history_path = run_dir / HISTORY_FILENAME
    if history_path.is_file():
        outputs_names["history"] = history_path.name
        downloads["history"] = f"/api/runs/{run_id}/download/history"

    return RunStatusResponse(
        run_id=record.run_id,
        status=record.status.value,
        current_phase=record.current_phase,
        run_dir=str(record.run_dir),
        created_at=record.created_at.isoformat() if record.created_at else None,
        started_at=record.started_at.isoformat() if record.started_at else None,
        finished_at=record.finished_at.isoformat() if record.finished_at else None,
        error=record.error,
        outputs=outputs_names,
        downloads=downloads,
    )

@app.get("/api/runs/{run_id}/download/history")
def download_history(run_id: str):
    validate_run_id(run_id)
    run_dir = get_run_dir(run_id)

    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")

    path = run_dir / HISTORY_FILENAME
    if not path.is_file():
        raise HTTPException(status_code=404, detail="History file not available.")

    return FileResponse(
        path=str(path),
        media_type="application/x-ndjson; charset=utf-8",
        filename=path.name,
    )


@app.get("/api/runs/{run_id}/chat/history", response_model=ChatHistoryResponse)
def get_chat_history(run_id: str, limit: int = Query(default=200, ge=1, le=2000)):
    validate_run_id(run_id)
    run_dir = get_run_dir(run_id)

    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")

    history_path = get_history_path(run_dir)
    try:
        messages = load_history_messages(history_path, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ChatHistoryResponse(messages=messages)


@app.post("/api/runs/{run_id}/chat", response_model=ChatSendResponse)
def chat(run_id: str, payload: ChatSendRequest):
    validate_run_id(run_id)
    run_dir = get_run_dir(run_id)

    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")

    _ensure_run_not_active(run_id)

    history_path = get_history_path(run_dir)
    lock = _get_chat_lock(run_id)
    with lock:
        try:
            history = load_history(history_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        try:
            chat_session = GENAI.chats.create(model=os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview"), history=history)
            response = chat_session.send_message(payload.message)
            reply = response.text or ""
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        try:
            append_message(history_path, role="user", text=payload.message)
            append_message(history_path, role="model", text=reply)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to persist chat history: {e}")

    return ChatSendResponse(reply=reply)


@app.get("/api/runs/{run_id}/download/{kind}")
def download_output(run_id: str, kind: str):
    validate_run_id(run_id)
    run_dir = get_run_dir(run_id)

    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")

    outputs = find_key_outputs(run_dir)
    path = outputs.get(kind)
    if not path:
        raise HTTPException(status_code=404, detail="File not available.")

    return FileResponse(
        path=str(path),
        media_type="text/markdown; charset=utf-8",
        filename=Path(path).name,
    )
