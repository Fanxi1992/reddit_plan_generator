# Reddit Marketing Plan Workflow

This repo contains a 4-phase workflow (`workflow1.py` ~ `workflow4.py`) that generates a Reddit marketing/content plan from a product context.

## One-click CLI run (recommended for local)

1) Edit `inputs/product_context.md` (English).
2) Run:

```bash
python run_all.py
```

Outputs are saved under `runs/<run_id>/`.

## Backend (FastAPI)

Start the API server:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### API flow

1) Get default prompts (per-phase big strings):
- `GET /api/prompts`

2) Start a run (async by default):
- `POST /api/runs`

Example request body:

```json
{
  "product_context_md": "[Client Product Data]\\nProduct Name: ...",
  "prompt_overrides": {},
  "wait": false
}
```

3) Poll status:
- `GET /api/runs/{run_id}`

4) Download outputs (available after success):
- `GET /api/runs/{run_id}/download/part1`
- `GET /api/runs/{run_id}/download/part2`
- `GET /api/runs/{run_id}/download/final`

## Notes

- The backend has no user system and no database (state is stored in `runs/<run_id>/run_state.json`).
- To avoid in-memory state issues, run Uvicorn with a single worker (default).

