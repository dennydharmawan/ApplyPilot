from __future__ import annotations

from types import SimpleNamespace

from applypilot.database import init_db
from applypilot.enrichment import detail
from applypilot.enrichment.detail import (
    _commit_enrich_result,
    list_enrich_leftovers,
    scrape_detail_page,
    write_enrich,
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


class _FakePage:
    url = "https://example.com/jobs/hr-analyst"

    def __init__(self, status=200, goto_error=None):
        self._status = status
        self._goto_error = goto_error

    def goto(self, url, timeout=None):
        if self._goto_error:
            raise self._goto_error
        return SimpleNamespace(status=self._status)

    def wait_for_load_state(self, *args, **kwargs):
        return None

    def title(self):
        return "HR Analyst"

    def query_selector_all(self, sel):
        return []

    def query_selector(self, sel):
        return None


def test_partial_enrich_preserves_application_url(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn, application_url="https://example.com/jobs/hr-analyst")

    _commit_enrich_result(
        conn,
        url,
        {
            "status": "partial",
            "full_description": "Full JD",
            "application_url": None,
        },
        "2026-08-20T00:00:00+00:00",
    )

    row = conn.execute(
        "SELECT full_description, application_url, detail_scraped_at FROM jobs"
    ).fetchone()
    assert row["full_description"] == "Full JD"
    assert row["application_url"] == "https://example.com/jobs/hr-analyst"
    assert row["detail_scraped_at"] == "2026-08-20T00:00:00+00:00"


def test_enrich_overwrites_application_url_when_found(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn, application_url="https://example.com/jobs/hr-analyst")

    _commit_enrich_result(
        conn,
        url,
        {
            "status": "ok",
            "full_description": "Full JD",
            "application_url": "https://boards.example.com/apply/1",
        },
        "2026-08-20T00:00:00+00:00",
    )

    row = conn.execute("SELECT application_url FROM jobs").fetchone()
    assert row["application_url"] == "https://boards.example.com/apply/1"


def test_write_enrich_sets_description_and_clears_error(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn, detail_error="needs_cursor_extraction")

    write_enrich(
        url,
        full_description="Extracted JD",
        application_url="https://boards.example.com/apply/1",
        conn=conn,
    )

    row = conn.execute(
        "SELECT full_description, application_url, detail_scraped_at, detail_error FROM jobs"
    ).fetchone()
    assert row["full_description"] == "Extracted JD"
    assert row["application_url"] == "https://boards.example.com/apply/1"
    assert row["detail_scraped_at"] is not None
    assert row["detail_error"] is None


def test_write_enrich_coalesce_application_url(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn, application_url="https://example.com/jobs/hr-analyst")

    write_enrich(url, full_description="Extracted JD", conn=conn)

    row = conn.execute("SELECT full_description, application_url FROM jobs").fetchone()
    assert row["full_description"] == "Extracted JD"
    assert row["application_url"] == "https://example.com/jobs/hr-analyst"


def test_write_enrich_rejects_unknown_url(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    try:
        write_enrich("https://missing.example/job", full_description="JD", conn=conn)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Unknown job URL" in str(exc)


def test_write_enrich_requires_a_field(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn)
    try:
        write_enrich(url, conn=conn)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Need full_description or application_url" in str(exc)


def test_retryable_http_does_not_stamp_scraped_at(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn)

    result = scrape_detail_page(_FakePage(status=503), url)
    assert result["status"] == "error"
    assert result["retryable"] is True
    assert result["error"] == "HTTP 503"

    _commit_enrich_result(conn, url, result, "2026-08-24T00:00:00+00:00")

    row = conn.execute("SELECT detail_scraped_at, detail_error FROM jobs").fetchone()
    assert row["detail_scraped_at"] is None
    assert row["detail_error"] == "HTTP 503"


def test_timeout_does_not_stamp_scraped_at(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn)

    result = scrape_detail_page(
        _FakePage(goto_error=TimeoutError("Timeout 45000ms exceeded")),
        url,
    )
    assert result["retryable"] is True
    assert result["error"] == "timeout"

    _commit_enrich_result(conn, url, result, "2026-08-24T00:00:00+00:00")
    row = conn.execute("SELECT detail_scraped_at, detail_error FROM jobs").fetchone()
    assert row["detail_scraped_at"] is None
    assert row["detail_error"] == "timeout"


def test_permanent_http_stamps_scraped_at(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    url = _insert_job(conn)

    result = scrape_detail_page(_FakePage(status=404), url)
    assert result.get("retryable") is not True
    assert result["error"] == "HTTP 404"

    _commit_enrich_result(conn, url, result, "2026-08-24T00:00:00+00:00")
    row = conn.execute("SELECT detail_scraped_at, detail_error FROM jobs").fetchone()
    assert row["detail_scraped_at"] == "2026-08-24T00:00:00+00:00"
    assert row["detail_error"] == "HTTP 404"


def test_tier3_gone_needs_cursor_extraction():
    assert not hasattr(detail, "extract_with_llm")
    result = scrape_detail_page(_FakePage(), "https://example.com/jobs/hr-analyst")
    assert result["status"] == "error"
    assert result["error"] == "needs_cursor_extraction"
    assert result.get("tier_used") is None


def test_list_enrich_leftovers_skips_retryable(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    leftover = _insert_job(
        conn,
        url="https://example.com/jobs/leftover",
        detail_scraped_at="2026-08-24T00:00:00+00:00",
        detail_error="needs_cursor_extraction",
    )
    _insert_job(
        conn,
        url="https://example.com/jobs/retryable",
        detail_error="HTTP 503",
    )
    _insert_job(
        conn,
        url="https://example.com/jobs/done",
        full_description="JD",
        detail_scraped_at="2026-08-24T00:00:00+00:00",
    )

    rows = list_enrich_leftovers(conn=conn)
    assert [r["url"] for r in rows] == [leftover]
