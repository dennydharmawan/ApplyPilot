"""Job fit scores persist through write_score. Judgment lives in the Score Pipeline Skill."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from applypilot.database import get_connection, get_jobs_by_stage

SCORE_REMOVED_MSG = "Scoring is no longer an API LLM stage. Use the Score Pipeline Skill."


def write_score(
    url: str,
    score: int,
    keywords: str,
    reasoning: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    if score not in range(1, 11):
        raise ValueError("score must be an integer from 1 to 10")
    if not url:
        raise ValueError("url is required")

    if conn is None:
        conn = get_connection()

    if conn.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)).fetchone() is None:
        raise ValueError(f"Unknown job URL: {url}")

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET fit_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ?",
        (score, f"{keywords}\n{reasoning}", now, url),
    )
    conn.commit()


def list_pending_scores(
    conn: sqlite3.Connection | None = None,
    limit: int = 0,
) -> list[dict]:
    return get_jobs_by_stage(conn=conn, stage="pending_score", limit=limit)
