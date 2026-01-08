# Reddit Paid Single-Subreddit Workflow

This repo contains a paid-delivery workflow that generates **one best Reddit post + an OP-only engagement kit** for a **locked target subreddit**, based on:
- upfront pre-materials (plan, product docs, constraints, links)
- real subreddit rules + top/hot post/comment corpus (via PRAW)
- multi-stage Gemini revisions (dossier → draft → mod review → revise → final → engagement kit)

## Backend (FastAPI)

Start the API server:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### API flow

1) Get default prompts (per-stage big strings):
- `GET /api/prompts`

2) Start a run (async by default):
- `POST /api/runs`

Example request body:

```json
{
  "target_subreddit": "CrewAI",
  "pre_materials": "Draft plan... product docs... constraints... links...",
  "options": {
    "top_time_filter": "month",
    "top_posts_limit": 20,
    "hot_posts_limit": 8,
    "comments_per_post": 7,
    "replies_per_comment": 2,
    "comment_reply_depth": 2
  },
  "prompt_overrides": {},
  "wait": false
}
```

3) Poll status:
- `GET /api/runs/{run_id}`

4) Download outputs (available after success, by key):
- `GET /api/runs/{run_id}/download/post_final`
- `GET /api/runs/{run_id}/download/engagement_kit`
- `GET /api/runs/{run_id}/download/subreddit_dossier`
- `GET /api/runs/{run_id}/download/mod_review`
- `GET /api/runs/{run_id}/download/product_brief`

## Notes

- The backend has no user system and no database (state is stored in `runs/<run_id>/run_state.json`).
- Upfront `pre_materials` are persisted to `pre_materials.md` in the run folder; only the extracted `product_brief.md` is used as authoritative chat context for the run.
- Chat history is appended per run in `runs/<run_id>/chat_history.jsonl` and is used for `/api/runs/{run_id}/chat` follow-ups.
- To avoid in-memory state issues, run Uvicorn with a single worker (default).

