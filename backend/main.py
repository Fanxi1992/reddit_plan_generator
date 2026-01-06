from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .chat_history import HISTORY_FILENAME
from .prompts import load_default_prompts
from .runner import RunAlreadyRunningError, RunManager, RunNotFoundError, RunStatus
from .schemas import PromptsResponse, RunCreateRequest, RunCreateResponse, RunStatusResponse
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


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/prompts", response_model=PromptsResponse)
def get_prompts():
    return PromptsResponse(prompts=load_default_prompts())


@app.post("/api/runs", response_model=RunCreateResponse)
def create_run(payload: RunCreateRequest):
    try:
        record = RUNS.start_run(
            product_context_md=payload.product_context_md,
            prompt_overrides=payload.prompt_overrides,
            run_id=payload.run_id,
            wait=payload.wait,
        )
    except RunAlreadyRunningError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    downloads: dict[str, str] = {}
    if payload.wait and record.status == RunStatus.SUCCEEDED:
        downloads = {
            "part1": f"/api/runs/{record.run_id}/download/part1",
            "part2": f"/api/runs/{record.run_id}/download/part2",
            "final": f"/api/runs/{record.run_id}/download/final",
        }

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
