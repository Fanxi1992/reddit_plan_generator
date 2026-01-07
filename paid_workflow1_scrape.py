from __future__ import annotations

import datetime
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import praw
import prawcore
from dotenv import load_dotenv

from backend.chat_history import append_message, get_history_path, load_history


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_attr(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return None


def normalize_subreddit_name(raw: str) -> str:
    name = (raw or "").strip()
    if name.lower().startswith("r/"):
        name = name[2:]
    name = name.strip()
    if not name:
        raise ValueError("target_subreddit is empty")
    if any(c.isspace() for c in name):
        raise ValueError("target_subreddit must not contain whitespace")
    return name


def classify_post(submission: Any) -> str:
    if safe_attr(submission, "is_self"):
        return "text"
    hint = (safe_attr(submission, "post_hint") or "").lower()
    if "image" in hint:
        return "image"
    if "video" in hint:
        return "video"
    url = (safe_attr(submission, "url") or "").lower()
    if url.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return "image"
    return "link"


def truncate(text: str, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    cleaned = text.replace("\r\n", "\n").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "…"


def get_reddit() -> praw.Reddit:
    if not os.getenv("REDDIT_CLIENT_ID"):
        raise RuntimeError("Missing Reddit credentials in environment (.env): REDDIT_CLIENT_ID is required.")
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=f"script:paid_single_sub_workflow:v1.0 (by /u/{os.getenv('REDDIT_USERNAME', 'bot')})",
        username=os.getenv("REDDIT_USERNAME"),
        password=os.getenv("REDDIT_PASSWORD"),
    )


def fetch_rules(subreddit: Any) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for rule in list(subreddit.rules):
        rules.append(
            {
                "short_name": safe_attr(rule, "short_name") or "",
                "description": safe_attr(rule, "description") or "",
            }
        )
    return rules


def rules_to_markdown(subreddit_name: str, rules: list[dict[str, Any]]) -> str:
    lines: list[str] = [f"# Subreddit Rules: r/{subreddit_name}", ""]
    if not rules:
        lines.append("_No structured rules returned by API._")
        return "\n".join(lines).strip() + "\n"
    for idx, rule in enumerate(rules, start=1):
        title = (rule.get("short_name") or "").strip() or "Untitled"
        desc = (rule.get("description") or "").strip()
        lines.append(f"{idx}. **{title}**")
        if desc:
            lines.append(f"   - {desc}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def fetch_posts(
    subreddit: Any,
    *,
    top_time_filter: str,
    top_posts_limit: int,
    hot_posts_limit: int,
) -> list[Any]:
    seen: set[str] = set()
    collected: list[Any] = []

    def consider(submission: Any) -> None:
        sid = safe_attr(submission, "id")
        if not isinstance(sid, str) or not sid:
            return
        if sid in seen:
            return
        if safe_attr(submission, "stickied"):
            return
        seen.add(sid)
        collected.append(submission)

    for submission in subreddit.top(time_filter=top_time_filter, limit=top_posts_limit):
        consider(submission)

    if hot_posts_limit > 0:
        for submission in subreddit.hot(limit=hot_posts_limit):
            consider(submission)

    return collected


def fetch_comment_tree(
    submission: Any,
    *,
    comments_per_post: int,
    replies_per_comment: int,
    comment_reply_depth: int,
) -> list[dict[str, Any]]:
    try:
        submission.comment_sort = "top"
    except Exception:
        pass

    submission.comments.replace_more(limit=0)
    top_level = list(submission.comments[:comments_per_post])

    def comment_to_record(comment: Any) -> dict[str, Any]:
        author = safe_attr(comment, "author")
        author_name = safe_attr(author, "name") if author else None
        rec: dict[str, Any] = {
            "id": safe_attr(comment, "id"),
            "author": author_name,
            "score": safe_attr(comment, "score"),
            "body": truncate(safe_attr(comment, "body") or "", 900),
            "created_utc": safe_attr(comment, "created_utc"),
            "replies": [],
        }

        if comment_reply_depth >= 2:
            replies: list[Any] = list(getattr(comment, "replies", []) or [])
            chosen = replies[:replies_per_comment] if replies_per_comment > 0 else []
            for reply in chosen:
                r_author = safe_attr(reply, "author")
                r_author_name = safe_attr(r_author, "name") if r_author else None
                rec["replies"].append(
                    {
                        "id": safe_attr(reply, "id"),
                        "author": r_author_name,
                        "score": safe_attr(reply, "score"),
                        "body": truncate(safe_attr(reply, "body") or "", 600),
                        "created_utc": safe_attr(reply, "created_utc"),
                    }
                )
        return rec

    return [comment_to_record(c) for c in top_level]


def build_corpus_excerpt(posts: list[dict[str, Any]], *, max_posts: int = 10) -> str:
    lines: list[str] = ["# Corpus Excerpt (Top Posts + Comment Snippets)", ""]
    chosen = posts[:max_posts]
    for idx, post in enumerate(chosen, start=1):
        lines.append(f"## Post {idx}: {post.get('title','').strip()}")
        lines.append(f"- type: {post.get('post_type')}")
        flair = (post.get("flair") or "").strip()
        if flair:
            lines.append(f"- flair: {flair}")
        lines.append(f"- score: {post.get('score')} | comments: {post.get('num_comments')}")
        lines.append(f"- permalink: {post.get('permalink')}")
        body = (post.get("selftext") or "").strip()
        if body:
            lines.append("")
            lines.append("Body (snippet):")
            lines.append(truncate(body, 450))
        lines.append("")
        lines.append("Top comments (snippets):")
        comments = post.get("comments") or []
        for c_idx, c in enumerate(comments[:3], start=1):
            author = c.get("author") or "[deleted]"
            lines.append(f"- C{c_idx} {author} (score {c.get('score')}): {truncate(c.get('body') or '', 220)}")
            replies = c.get("replies") or []
            for r_idx, r in enumerate(replies[:1], start=1):
                r_author = r.get("author") or "[deleted]"
                lines.append(f"  - R{r_idx} {r_author}: {truncate(r.get('body') or '', 180)}")
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
    options = config.get("options") if isinstance(config.get("options"), dict) else {}

    top_time_filter = str(options.get("top_time_filter") or "month")
    top_posts_limit = int(options.get("top_posts_limit") or 20)
    hot_posts_limit = int(options.get("hot_posts_limit") or 8)
    comments_per_post = int(options.get("comments_per_post") or 7)
    replies_per_comment = int(options.get("replies_per_comment") or 2)
    comment_reply_depth = int(options.get("comment_reply_depth") or 2)

    print(f"[scrape] Target subreddit: r/{target}")
    print(
        f"[scrape] Sampling: top({top_time_filter})={top_posts_limit}, hot={hot_posts_limit}, "
        f"comments/post={comments_per_post}, replies/comment={replies_per_comment}, depth={comment_reply_depth}"
    )

    reddit = get_reddit()

    try:
        subreddit = reddit.subreddit(target)
        _ = subreddit.display_name  # trigger fetch early
    except prawcore.exceptions.NotFound:
        print(f"Error: r/{target} not found (404).")
        return 1
    except prawcore.exceptions.Forbidden:
        print(f"Error: r/{target} is private/banned (403).")
        return 1

    rules = fetch_rules(subreddit)
    rules_md = rules_to_markdown(target, rules)

    meta: dict[str, Any] = {
        "subreddit": target,
        "title": safe_attr(subreddit, "title"),
        "public_description": safe_attr(subreddit, "public_description"),
        "subscribers": safe_attr(subreddit, "subscribers"),
        "active_user_count": safe_attr(subreddit, "active_user_count"),
        "created_utc": safe_attr(subreddit, "created_utc"),
        "over18": safe_attr(subreddit, "over18"),
        "lang": safe_attr(subreddit, "lang"),
        "submission_type": safe_attr(subreddit, "submission_type"),
        "allow_images": safe_attr(subreddit, "allow_images"),
        "allow_videos": safe_attr(subreddit, "allow_videos"),
        "allow_videogifs": safe_attr(subreddit, "allow_videogifs"),
        "allow_polls": safe_attr(subreddit, "allow_polls"),
        "link_flair_enabled": safe_attr(subreddit, "link_flair_enabled"),
        "scraped_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }

    submissions = fetch_posts(
        subreddit,
        top_time_filter=top_time_filter,
        top_posts_limit=top_posts_limit,
        hot_posts_limit=hot_posts_limit,
    )
    print(f"[scrape] Posts collected: {len(submissions)}")

    post_type_counter: Counter[str] = Counter()
    flair_counter: Counter[str] = Counter()
    posts_out: list[dict[str, Any]] = []

    for idx, submission in enumerate(submissions, start=1):
        print(f"[scrape] ({idx}/{len(submissions)}) {submission.id} …", end="", flush=True)
        post_type = classify_post(submission)
        post_type_counter[post_type] += 1

        flair = safe_attr(submission, "link_flair_text") or safe_attr(submission, "flair_text") or ""
        flair = str(flair or "").strip()
        if flair:
            flair_counter[flair] += 1

        try:
            comments = fetch_comment_tree(
                submission,
                comments_per_post=comments_per_post,
                replies_per_comment=replies_per_comment,
                comment_reply_depth=comment_reply_depth,
            )
        except Exception as e:
            print(f" error(comments): {e}")
            comments = []

        post_record: dict[str, Any] = {
            "id": safe_attr(submission, "id"),
            "title": safe_attr(submission, "title") or "",
            "selftext": truncate(safe_attr(submission, "selftext") or "", 2200),
            "url": safe_attr(submission, "url"),
            "permalink": f"https://www.reddit.com{safe_attr(submission, 'permalink')}",
            "created_utc": safe_attr(submission, "created_utc"),
            "score": safe_attr(submission, "score"),
            "upvote_ratio": safe_attr(submission, "upvote_ratio"),
            "num_comments": safe_attr(submission, "num_comments"),
            "post_type": post_type,
            "flair": flair or None,
            "comments": comments,
        }
        posts_out.append(post_record)
        print(" ok")

    meta["observed_post_types"] = dict(post_type_counter)
    meta["observed_top_flairs"] = [k for k, _ in flair_counter.most_common(10)]

    write_json(run_dir / "subreddit_meta.json", meta)
    write_json(run_dir / "subreddit_rules.json", rules)
    (run_dir / "subreddit_rules.md").write_text(rules_md, encoding="utf-8")
    write_json(run_dir / "corpus.json", posts_out)
    (run_dir / "corpus_excerpt.md").write_text(build_corpus_excerpt(posts_out, max_posts=10), encoding="utf-8")

    # Append a compact progress note to chat history (avoid storing full corpus in chat history).
    history_path = get_history_path(run_dir)
    history = load_history(history_path)
    if history is not None:
        append_message(
            history_path,
            role="user",
            text=(
                "[Stage] Subreddit scrape complete.\n\n"
                f"Target: r/{target}\n"
                f"Collected posts: {len(posts_out)} (top={top_posts_limit}, hot={hot_posts_limit})\n"
                f"Observed post types: {dict(post_type_counter)}\n"
                "Artifacts saved: subreddit_meta.json, subreddit_rules.md, corpus_excerpt.md, corpus.json\n"
            ),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

