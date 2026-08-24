from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from applypilot.database import close_connection, init_db
from applypilot.scoring.scorer import (
    SCORE_REMOVED_MSG,
    list_pending_scores,
    write_score,
)


def _insert_job(conn, url="https://example.com/jobs/hr-analyst", **fields):
    cols = ["url", "title", "site", "strategy"]
    vals = [
        url,
        fields.pop("title", "HR Analyst"),
        fields.pop("site", "Acme Corp"),
        fields.pop("strategy", "hiringcafe"),
    ]
    extra = list(fields)
    cols.extend(extra)
    vals.extend(fields[k] for k in extra)
    placeholders = ", ".join("?" * len(cols))
    conn.execute(
        f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()
    return url


def test_write_score_persists_folded_reasoning(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn, full_description="JD")

    write_score(url, 8, "python, sql", "Strong match on core skills.", conn=conn)

    row = conn.execute(
        "SELECT fit_score, score_reasoning, scored_at FROM jobs"
    ).fetchone()
    assert row["fit_score"] == 8
    assert row["score_reasoning"] == "python, sql\nStrong match on core skills."
    assert row["scored_at"]


def test_write_score_overwrite_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn, full_description="JD")
    write_score(url, 4, "k1", "first", conn=conn)
    write_score(url, 9, "k2", "second", conn=conn)
    write_score(url, 9, "k2", "second", conn=conn)

    row = conn.execute("SELECT fit_score, score_reasoning FROM jobs").fetchone()
    assert row["fit_score"] == 9
    assert row["score_reasoning"] == "k2\nsecond"


@pytest.mark.parametrize("score", [0, 11, -1])
def test_write_score_rejects_out_of_range(tmp_path, score):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn)
    with pytest.raises(ValueError, match="1 to 10"):
        write_score(url, score, "k", "r", conn=conn)
    assert conn.execute("SELECT fit_score FROM jobs").fetchone()["fit_score"] is None


def test_write_score_rejects_unknown_url(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    with pytest.raises(ValueError, match="Unknown job URL"):
        write_score("https://missing.example/job", 7, "k", "r", conn=conn)


def test_list_pending_scores_only_enriched_unscored(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    pending = _insert_job(
        conn,
        url="https://example.com/jobs/pending",
        full_description="JD",
    )
    _insert_job(
        conn,
        url="https://example.com/jobs/scored",
        full_description="JD",
        fit_score=7,
    )
    _insert_job(
        conn,
        url="https://example.com/jobs/no-desc",
        detail_scraped_at="2026-08-24T00:00:00+00:00",
    )

    rows = list_pending_scores(conn=conn, limit=0)
    assert [r["url"] for r in rows] == [pending]


def test_run_score_stage_does_not_import_llm():
    from applypilot.scoring import scorer

    assert not hasattr(scorer, "run_scoring")
    assert not hasattr(scorer, "score_job")
    assert "get_client" not in dir(scorer)


def _cli(tmp_path, *args):
    env = os.environ.copy()
    env["APPLYPILOT_DIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, "-m", "applypilot", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_score_write_cli(tmp_path):
    db = tmp_path / "applypilot.db"
    conn = init_db(db)
    url = _insert_job(conn, full_description="JD")
    close_connection(db)

    proc = _cli(
        tmp_path,
        "score-write",
        "--url",
        url,
        "--score",
        "8",
        "--keywords",
        "python, sql",
        "--reasoning",
        "Strong match",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    row = sqlite3.connect(db).execute(
        "SELECT fit_score, score_reasoning FROM jobs"
    ).fetchone()
    assert row[0] == 8
    assert row[1] == "python, sql\nStrong match"


def test_score_write_cli_rejects_bad_score(tmp_path):
    db = tmp_path / "applypilot.db"
    conn = init_db(db)
    url = _insert_job(conn)
    close_connection(db)

    proc = _cli(
        tmp_path,
        "score-write",
        "--url",
        url,
        "--score",
        "99",
        "--keywords",
        "k",
        "--reasoning",
        "r",
    )
    assert proc.returncode == 1
    assert "1 to 10" in proc.stdout + proc.stderr


def test_score_pending_cli_json_lines(tmp_path):
    db = tmp_path / "applypilot.db"
    conn = init_db(db)
    url = _insert_job(conn, title="HR Analyst", site="Acme Corp", full_description="JD")
    close_connection(db)

    proc = _cli(tmp_path, "score-pending")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = json.loads(proc.stdout.strip().splitlines()[0])
    assert line == {"url": url, "title": "HR Analyst", "site": "Acme Corp"}


def test_enrich_write_cli(tmp_path):
    db = tmp_path / "applypilot.db"
    conn = init_db(db)
    url = _insert_job(conn, detail_error="needs_cursor_extraction")
    close_connection(db)

    proc = _cli(
        tmp_path,
        "enrich-write",
        "--url",
        url,
        "--full-description",
        "Extracted JD",
        "--application-url",
        "https://boards.example.com/apply/1",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    row = sqlite3.connect(db).execute(
        "SELECT full_description, application_url, detail_error FROM jobs"
    ).fetchone()
    assert row[0] == "Extracted JD"
    assert row[1] == "https://boards.example.com/apply/1"
    assert row[2] is None


def test_enrich_leftovers_cli_json_lines(tmp_path):
    db = tmp_path / "applypilot.db"
    conn = init_db(db)
    url = _insert_job(
        conn,
        title="HR Analyst",
        site="Acme Corp",
        detail_scraped_at="2026-08-24T00:00:00+00:00",
        detail_error="needs_cursor_extraction",
    )
    close_connection(db)

    proc = _cli(tmp_path, "enrich-leftovers")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = json.loads(proc.stdout.strip().splitlines()[0])
    assert line == {"url": url, "title": "HR Analyst", "site": "Acme Corp"}


def test_run_score_exits_without_llm(tmp_path):
    proc = _cli(tmp_path, "run", "score")
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert SCORE_REMOVED_MSG in combined
    assert "codex" not in combined.lower()
    assert "GEMINI_API_KEY" not in combined
