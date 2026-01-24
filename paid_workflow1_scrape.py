from __future__ import annotations

import datetime
import html
import json
import os
import random
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import requests
from apify_client import ApifyClient
from dotenv import load_dotenv

from backend.chat_history import append_message, get_history_path, load_history

REDDIT_BASE_URL = "https://www.reddit.com"

DEFAULT_REQUEST_TIMEOUT_SEC = float(os.environ.get("REDDIT_JSON_TIMEOUT_SEC", "15") or "15")
DEFAULT_RETRY_ON_429 = int(os.environ.get("REDDIT_JSON_RETRY_ON_429", "2") or "2")
DEFAULT_BACKOFF_ON_429_RANGE_SEC = (10.0, 20.0)
DEFAULT_RETRY_ON_TRANSIENT = int(os.environ.get("REDDIT_JSON_RETRY_ON_TRANSIENT", "1") or "1")
DEFAULT_BACKOFF_ON_TRANSIENT_RANGE_SEC = (1.0, 2.0)
DEFAULT_SLEEP_RANGE_SEC = (0.5, 1.5)

APIFY_ACTOR_ID = (os.environ.get("APIFY_ACTOR_ID") or "oAuCIx3ItNrs2okjQ").strip()

MAX_POSTS_TOP_WEEK = 20
POST_BODY_MAX_CHARS = 4000
APIFY_SCROLL_TIMEOUT_SEC = 40


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return 0


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return None


def normalize_subreddit_name(raw: str) -> str:
    name = (raw or "").strip()
    if name.lower().startswith("r/"):
        name = name[2:]
    name = name.strip().strip("/")
    if not name:
        raise ValueError("target_subreddit is empty")
    if any(c.isspace() for c in name):
        raise ValueError("target_subreddit must not contain whitespace")
    return name


def normalize_text(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return text.replace("\r\n", "\n")


def _fenced_block(text: str, *, lang: str = "text") -> list[str]:
    max_ticks = 0
    current = 0
    for ch in text:
        if ch == "`":
            current += 1
            max_ticks = max(max_ticks, current)
        else:
            current = 0

    fence = "`" * max(3, max_ticks + 1)
    header = f"{fence}{lang}".rstrip()
    return [header, text, fence]


def create_reddit_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    session.cookies.set("over18", "1")
    return session


def _status_label(code: int) -> str:
    if code == 404:
        return "404 Not Found"
    if code == 403:
        return "403 Forbidden"
    if code == 429:
        return "429 Too Many Requests"
    return f"HTTP {code}"


def _fetch_json(
    session: requests.Session,
    url: str,
    *,
    timeout_sec: float = DEFAULT_REQUEST_TIMEOUT_SEC,
    retry_on_429: int = DEFAULT_RETRY_ON_429,
    backoff_on_429_range_sec: tuple[float, float] = DEFAULT_BACKOFF_ON_429_RANGE_SEC,
    retry_on_transient: int = DEFAULT_RETRY_ON_TRANSIENT,
    backoff_on_transient_range_sec: tuple[float, float] = DEFAULT_BACKOFF_ON_TRANSIENT_RANGE_SEC,
) -> tuple[int, dict | None, str | None]:
    attempts = 1 + max(0, retry_on_429) + max(0, retry_on_transient)
    seen_429 = 0
    seen_transient = 0

    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=timeout_sec)
        except requests.RequestException as e:
            if seen_transient < retry_on_transient and attempt < attempts:
                seen_transient += 1
                time.sleep(random.uniform(*backoff_on_transient_range_sec))
                continue
            return 0, None, str(e)

        if response.status_code == 429:
            if seen_429 < retry_on_429 and attempt < attempts:
                seen_429 += 1
                time.sleep(random.uniform(*backoff_on_429_range_sec))
                continue
            return 429, None, None

        if response.status_code != 200:
            return response.status_code, None, None

        try:
            data = response.json()
        except ValueError:
            snippet = (response.text or "")[:200].replace("\n", " ")
            return (
                0,
                None,
                f"Invalid JSON (content-type={response.headers.get('content-type')!r}) snippet={snippet!r}",
            )

        if not isinstance(data, dict):
            return 0, None, f"Unexpected JSON type: {type(data).__name__}"

        return 200, data, None

    return 0, None, "Unknown fetch error"


def fetch_about_data(session: requests.Session, subreddit_name: str) -> dict[str, Any]:
    url = f"{REDDIT_BASE_URL}/r/{subreddit_name}/about.json?raw_json=1"
    status_code, payload, error = _fetch_json(session, url)
    if error:
        raise RuntimeError(f"about.json fetch error: {error}")
    if status_code != 200 or payload is None:
        raise RuntimeError(f"about.json failed: {_status_label(status_code)}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("about.json missing 'data' object")
    return data  # type: ignore[return-value]


def fetch_rules(session: requests.Session, subreddit_name: str) -> list[dict[str, Any]]:
    url = f"{REDDIT_BASE_URL}/r/{subreddit_name}/about/rules.json?raw_json=1"
    status_code, payload, error = _fetch_json(session, url)
    if error:
        raise RuntimeError(f"rules.json fetch error: {error}")
    if status_code != 200 or payload is None:
        raise RuntimeError(f"rules.json failed: {_status_label(status_code)}")

    rules_raw = payload.get("rules", [])
    if not isinstance(rules_raw, list):
        return []

    rules: list[dict[str, Any]] = []
    for raw in rules_raw:
        if not isinstance(raw, dict):
            continue
        rules.append(
            {
                "short_name": html.unescape(str(raw.get("short_name") or "")),
                "description": html.unescape(str(raw.get("description") or "")),
            }
        )
    return rules


def rules_to_markdown(subreddit_name: str, rules: list[dict[str, Any]]) -> str:
    lines: list[str] = [f"# Subreddit Rules: r/{subreddit_name}", ""]
    if not rules:
        lines.append("_No structured rules returned by API._")
        return "\n".join(lines).strip() + "\n"
    for idx, rule in enumerate(rules, start=1):
        title = (str(rule.get("short_name") or "")).strip() or "Untitled"
        desc = (str(rule.get("description") or "")).strip()
        lines.append(f"{idx}. **{title}**")
        if desc:
            lines.append(f"   - {desc}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_week_url(subreddit_name: str) -> str:
    clean = subreddit_name.strip().lstrip("/")
    if clean.lower().startswith("r/"):
        clean = clean[2:]
    clean = clean.strip().strip("/")
    return f"https://www.reddit.com/r/{clean}/top/?t=week"


def fetch_top_week_posts_via_apify(
    subreddit_name: str,
    *,
    max_items: int,
    scroll_timeout_sec: int = APIFY_SCROLL_TIMEOUT_SEC,
) -> list[dict[str, Any]]:
    token = (os.environ.get("APIFY_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Missing APIFY_TOKEN in environment/.env")
    if not APIFY_ACTOR_ID:
        raise RuntimeError("Missing APIFY_ACTOR_ID in environment")

    url = build_week_url(subreddit_name)
    apify = ApifyClient(token)

    run_input = {
        "startUrls": [{"url": url}],
        "skipComments": True,
        "skipUserPosts": False,
        "skipCommunity": True,
        "searches": [],
        "ignoreStartUrls": False,
        "searchPosts": True,
        "searchComments": False,
        "searchCommunities": False,
        "searchUsers": False,
        "sort": "new",
        "includeNSFW": True,
        "maxItems": int(max_items),
        "maxPostCount": int(max_items),
        "maxComments": 0,
        "maxCommunitiesCount": 0,
        "maxUserCount": 0,
        "scrollTimeout": int(scroll_timeout_sec),
        "proxy": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        },
        "debugMode": False,
    }

    run = apify.actor(APIFY_ACTOR_ID).call(run_input=run_input)
    dataset_id = run.get("defaultDatasetId")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise RuntimeError(f"Apify run missing defaultDatasetId: {run!r}")

    items: list[dict[str, Any]] = []
    for raw in apify.dataset(dataset_id).iterate_items():
        if isinstance(raw, dict):
            items.append(raw)

    posts = [it for it in items if it.get("dataType") == "post"]
    return posts[:max_items]


def extract_post_id(url: str) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    match = re.search(r"/comments/([A-Za-z0-9]+)/", url)
    if match:
        return match.group(1)
    return None


def classify_post(post: dict[str, Any]) -> str:
    if bool(post.get("isVideo")):
        return "video"
    image_urls = post.get("imageUrls")
    if isinstance(image_urls, list) and len(image_urls) > 0:
        return "image"

    body = normalize_text(post.get("body") or "")
    if body.strip():
        return "text"

    url = str(post.get("url") or "").lower()
    if url.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return "image"
    return "link"


def build_corpus_excerpt(posts: list[dict[str, Any]]) -> str:
    lines: list[str] = ["# Corpus Excerpt (Reference Material: Top-week Posts)", ""]
    for idx, post in enumerate(posts, start=1):
        title = str(post.get("title") or "").strip()
        lines.append(f"## Post {idx}: {title}")
        lines.append(f"- id: {post.get('id')}")
        lines.append(f"- type: {post.get('post_type')}")

        flair = str(post.get("flair") or "").strip()
        if flair:
            lines.append(f"- flair: {flair}")

        lines.append(
            f"- score: {post.get('score')} | comments: {post.get('num_comments')} | upvote_ratio: {post.get('upvote_ratio')}"
        )
        lines.append(f"- permalink: {post.get('permalink')}")

        url = normalize_text(post.get("url") or "")
        if url:
            lines.append(f"- url: {url}")

        body = normalize_text(post.get("selftext") or "")
        lines.append("")
        lines.append("Body:")
        if body.strip():
            lines.extend(_fenced_block(body))
        else:
            lines.append("_No body / link-only post._")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    load_dotenv()

    run_dir = Path.cwd()
    config_path = run_dir / "run_config.json"
    if not config_path.is_file():
        print("Error: missing run_config.json (created by backend runner).")
        return 1

    config = read_json(config_path)
    target = normalize_subreddit_name(str(config.get("target_subreddit") or ""))
    print(f"[scrape] Target subreddit: r/{target}")
    print(f"[scrape] Sampling: top(week)={MAX_POSTS_TOP_WEEK} via Reddit JSON + Apify (no comments)")

    session = create_reddit_session()

    try:
        about_data = fetch_about_data(session, target)
    except Exception as e:
        print(f"Error: failed to fetch subreddit about.json for r/{target}: {e}")
        return 1

    time.sleep(random.uniform(*DEFAULT_SLEEP_RANGE_SEC))

    try:
        rules = fetch_rules(session, target)
        rules_md = rules_to_markdown(target, rules)
    except Exception as e:
        print(f"Warning: failed to fetch subreddit rules.json for r/{target}: {e}")
        rules = []
        rules_md = rules_to_markdown(target, rules)

    meta: dict[str, Any] = {
        "subreddit": target,
        "title": about_data.get("title"),
        "public_description": about_data.get("public_description"),
        "subscribers": _safe_int(about_data.get("subscribers")),
        "active_user_count": _safe_int(about_data.get("active_user_count") or about_data.get("accounts_active")),
        "created_utc": about_data.get("created_utc"),
        "over18": about_data.get("over18"),
        "lang": about_data.get("lang"),
        "submission_type": about_data.get("submission_type"),
        "allow_images": about_data.get("allow_images"),
        "allow_videos": about_data.get("allow_videos"),
        "allow_videogifs": about_data.get("allow_videogifs"),
        "allow_polls": about_data.get("allow_polls"),
        "link_flair_enabled": about_data.get("link_flair_enabled"),
        "scraped_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }

    try:
        apify_posts = fetch_top_week_posts_via_apify(target, max_items=MAX_POSTS_TOP_WEEK)
    except Exception as e:
        print(f"Error: failed to fetch top-week posts via Apify for r/{target}: {e}")
        return 1

    print(f"[scrape] Posts collected: {len(apify_posts)}")

    post_type_counter: Counter[str] = Counter()
    flair_counter: Counter[str] = Counter()
    posts_out: list[dict[str, Any]] = []

    for idx, post in enumerate(apify_posts, start=1):
        url = str(post.get("url") or "")
        pid = str(post.get("id") or "").strip() or (extract_post_id(url) or f"apify_{idx}")

        print(f"[scrape] ({idx}/{len(apify_posts)}) {pid} …", end="", flush=True)

        title = normalize_text(post.get("title") or "").strip()
        body = normalize_text(post.get("body") or "").strip()
        if POST_BODY_MAX_CHARS > 0 and len(body) > POST_BODY_MAX_CHARS:
            body = body[:POST_BODY_MAX_CHARS] + "...(truncated)"

        flair = str(post.get("flair") or "").strip()
        post_type = classify_post(post)
        post_type_counter[post_type] += 1
        if flair:
            flair_counter[flair] += 1

        post_record: dict[str, Any] = {
            "id": pid,
            "title": title,
            "selftext": body,
            "url": url,
            "permalink": url,
            "created_utc": post.get("created_utc") or post.get("createdUtc") or post.get("createdAt"),
            "score": _safe_int(post.get("upVotes")),
            "upvote_ratio": _safe_float(post.get("upVoteRatio")),
            "num_comments": _safe_int(post.get("numberOfComments")),
            "post_type": post_type,
            "flair": flair or None,
            "comments": [],
        }
        posts_out.append(post_record)
        print(" ok")

    meta["observed_post_types"] = dict(post_type_counter)
    meta["observed_top_flairs"] = [k for k, _ in flair_counter.most_common(10)]

    write_json(run_dir / "subreddit_meta.json", meta)
    write_json(run_dir / "subreddit_rules.json", rules)
    (run_dir / "subreddit_rules.md").write_text(rules_md, encoding="utf-8")
    write_json(run_dir / "corpus.json", posts_out)
    (run_dir / "corpus_excerpt.md").write_text(build_corpus_excerpt(posts_out), encoding="utf-8")

    history_path = get_history_path(run_dir)
    history = load_history(history_path)
    if history is not None:
        append_message(
            history_path,
            role="user",
            text=(
                "[Stage] Subreddit scrape complete.\n\n"
                f"Target: r/{target}\n"
                f"Collected posts: {len(posts_out)} (top_week={MAX_POSTS_TOP_WEEK}, source=apify)\n"
                f"Observed post types: {dict(post_type_counter)}\n"
                "Artifacts saved: subreddit_meta.json, subreddit_rules.md, corpus_excerpt.md, corpus.json\n"
            ),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

