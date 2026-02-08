from __future__ import annotations

import json
import os
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from google import genai

from .chat_history import HISTORY_FILENAME, append_message, get_history_path, load_history, load_history_messages
from .prompts import PROMPT_KEYS, load_default_prompts, load_prompts_file, merge_prompts
from .runner import RunAlreadyRunningError, RunManager, RunNotFoundError, RunStatus
from .schemas import (
    ChatHistoryResponse,
    ChatSendRequest,
    ChatSendResponse,
    EffectivePromptsRequest,
    PromptsResponse,
    StrategiesResponse,
    StrategyDef,
    RunCreateRequest,
    RunCreateResponse,
    RunRestoreResponse,
    RunStatusResponse,
 )
from .strategies import Stage, apply_strategy_spec, build_strategy_spec, list_strategies, validate_strategy_id
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


@app.post("/api/prompts/effective", response_model=PromptsResponse)
def get_effective_prompts(payload: EffectivePromptsRequest):
    """
    Return the *effective* prompt templates that will be used at runtime:
    - Merge default prompts with the provided prompt_overrides.
    - Inject the selected strategy_spec into the relevant stage prompts.
    - Keep all other placeholders (e.g. {{product_brief}}/{{subreddit_dossier}}) intact.
    """
    brief_mode = (payload.brief_mode or "extract").strip().lower()
    if brief_mode not in {"extract", "raw"}:
        brief_mode = "extract"

    skip_keys = {"brief_prompt"} if brief_mode == "raw" else None
    try:
        prompts = merge_prompts(load_default_prompts(), payload.prompt_overrides, skip_keys=skip_keys)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    strategy_id = (payload.strategy_id or "").strip() or "free"
    try:
        validate_strategy_id(strategy_id)
    except Exception:
        strategy_id = "free"
    strategy_notes = (payload.strategy_notes or "").strip() or None

    def inject(key: str, *, stage: Stage) -> None:
        spec = build_strategy_spec(strategy_id=strategy_id, strategy_notes=strategy_notes, stage=stage)
        prompts[key] = apply_strategy_spec(prompts.get(key, ""), strategy_spec=spec)

    inject("post_draft_prompt", stage="post_v1")
    inject("mod_review_prompt", stage="mod_review")
    inject("revise_prompt", stage="post_v2")
    inject("native_polish_prompt", stage="post_final")

    return PromptsResponse(prompts={k: prompts.get(k, "") for k in PROMPT_KEYS})


@app.get("/api/strategies", response_model=StrategiesResponse)
def get_strategies():
    try:
        catalog = list_strategies()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return StrategiesResponse(
        strategies=[
            StrategyDef(
                id=st.id,
                title=st.title,
                description=st.description,
                pov=st.pov,
                brand={
                    "min_mentions": st.brand.min_mentions,
                    "max_mentions": st.brand.max_mentions,
                    "allow_in_title": st.brand.allow_in_title,
                    "notes": st.brand.notes,
                },
                title_templates=list(st.title_templates),
                beats=list(st.beats),
                draft_template_md=st.draft_template_md,
            )
            for st in catalog
        ]
    )


@app.post("/api/runs", response_model=RunCreateResponse)
def create_run(payload: RunCreateRequest):
    try:
        options = payload.options.model_dump() if hasattr(payload.options, "model_dump") else payload.options.dict()
        record = RUNS.start_run(
            target_subreddit=payload.target_subreddit,
            pre_materials=payload.pre_materials,
            brief_mode=payload.brief_mode,
            options=options,
            prompt_overrides=payload.prompt_overrides,
            strategy_id=payload.strategy_id,
            strategy_notes=payload.strategy_notes,
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


@app.get("/api/runs/{run_id}/restore", response_model=RunRestoreResponse)
def restore_run(run_id: str):
    try:
        validate_run_id(run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    run_dir = get_run_dir(run_id)
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")

    config_path = run_dir / "run_config.json"
    prompts_path = run_dir / "prompts.json"
    pre_materials_path = run_dir / "pre_materials.md"

    if not config_path.is_file():
        raise HTTPException(status_code=404, detail="run_config.json not available; cannot restore.")
    if not prompts_path.is_file():
        raise HTTPException(status_code=404, detail="prompts.json not available; cannot restore.")
    if not pre_materials_path.is_file():
        raise HTTPException(status_code=404, detail="pre_materials.md not available; cannot restore.")

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to read run_config.json.")

    if not isinstance(config, dict):
        raise HTTPException(status_code=500, detail="Invalid run_config.json.")

    target_subreddit = config.get("target_subreddit")
    if not isinstance(target_subreddit, str) or not target_subreddit.strip():
        raise HTTPException(status_code=500, detail="Invalid run_config.json: missing target_subreddit.")
    target_subreddit = target_subreddit.strip()

    post_v1_mode_raw = config.get("post_v1_mode")
    post_v1_mode = post_v1_mode_raw.strip().lower() if isinstance(post_v1_mode_raw, str) else "generate"
    if post_v1_mode not in {"generate", "client_draft"}:
        post_v1_mode = "generate"

    brief_mode_raw = config.get("brief_mode")
    brief_mode = brief_mode_raw.strip().lower() if isinstance(brief_mode_raw, str) else "extract"
    if brief_mode not in {"extract", "raw"}:
        brief_mode = "extract"

    stop_after_mod_review = bool(config.get("stop_after_mod_review", False))

    strategy_id_raw = config.get("strategy_id")
    strategy_id = strategy_id_raw.strip() if isinstance(strategy_id_raw, str) else "free"
    if not strategy_id:
        strategy_id = "free"

    strategy_notes_raw = config.get("strategy_notes")
    strategy_notes = strategy_notes_raw.strip() if isinstance(strategy_notes_raw, str) else ""
    strategy_notes = strategy_notes or None

    post_v1_client_draft: str | None = None
    if post_v1_mode == "client_draft":
        filename = config.get("client_post_draft_filename")
        if not isinstance(filename, str) or not filename.strip():
            raise HTTPException(
                status_code=500,
                detail="Invalid run_config.json: missing client_post_draft_filename.",
            )
        draft_path = run_dir / filename
        if not draft_path.is_file():
            raise HTTPException(status_code=404, detail=f"{filename} not available; cannot restore.")
        post_v1_client_draft = draft_path.read_text(encoding="utf-8")

    try:
        prompts = load_prompts_file(prompts_path)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to read prompts.json.")

    missing_keys = [k for k in PROMPT_KEYS if k not in prompts]
    if missing_keys:
        raise HTTPException(status_code=500, detail=f"prompts.json missing keys: {missing_keys}")

    pre_materials = pre_materials_path.read_text(encoding="utf-8")

    return RunRestoreResponse(
        run_id=run_id,
        target_subreddit=target_subreddit,
        pre_materials=pre_materials,
        brief_mode=brief_mode,
        prompts={k: prompts[k] for k in PROMPT_KEYS},
        strategy_id=strategy_id,
        strategy_notes=strategy_notes,
        post_v1_mode=post_v1_mode,
        post_v1_client_draft=post_v1_client_draft,
        stop_after_mod_review=stop_after_mod_review,
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
            chat_session = GENAI.chats.create(model=os.environ.get("GEMINI_MODEL", "gemini-3-pro-preview"), history=history)
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
