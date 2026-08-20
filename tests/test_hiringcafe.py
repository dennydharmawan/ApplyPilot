from __future__ import annotations

import json
from pathlib import Path

import pytest

from applypilot.database import init_db
from applypilot.discovery.hiringcafe import (
    EmptyQueryError,
    Query,
    _parse_ssr_html,
    _persist,
    _Search,
    parse_run_query,
)

FIXTURE = Path(__file__).parent / "fixtures" / "hiringcafe_ssr.html"


class TestQueryParse:
    @pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
    def test_rejects_empty(self, raw):
        with pytest.raises(EmptyQueryError):
            Query.parse(raw)

    def test_accepts_stripped_keywords(self):
        q = Query.parse("  human resource  ")
        assert q.text == "human resource"


class TestParseRunQuery:
    def test_requires_query_only_when_discover_runs(self):
        with pytest.raises(EmptyQueryError):
            parse_run_query(None, ["discover"])

        with pytest.raises(EmptyQueryError):
            parse_run_query("   ", ["discover", "enrich"])

        assert parse_run_query(None, ["enrich", "score"]) is None
        assert parse_run_query("ignored", ["score"]) is None

    def test_returns_query_when_discover_runs(self):
        q = parse_run_query("backend", ["discover"])
        assert isinstance(q, Query)
        assert q.text == "backend"


class TestSearchState:
    def test_encodes_jakarta_place_and_remote_window(self):
        state = json.loads(_Search.compile(Query.parse("human resource")).search_state_json())
        loc = state["locations"][0]
        assert loc["id"] == "NhY1yZQBoEtHp_8UErPW"
        assert loc["workplace_types"] == ["Remote", "Hybrid", "Onsite"]
        assert loc["options"]["flexible_regions"] == [
            "anywhere_in_continent",
            "anywhere_in_world",
        ]
        assert "anywhere_in_country" not in loc["options"]["flexible_regions"]
        assert state["workplaceTypes"] == ["Remote", "Hybrid", "Onsite"]
        assert state["searchQuery"] == "human resource"
        assert state["dateFetchedPastNDays"] == 3
        assert "page" not in state


class TestParseSsrHtml:
    def test_maps_fixture_hits(self):
        html = FIXTURE.read_text(encoding="utf-8")
        page = _parse_ssr_html(html)

        assert page.is_last_page is True
        assert len(page.jobs) == 1

        job = page.jobs[0]
        assert job["url"] == "https://example.com/jobs/hr-analyst"
        assert job["application_url"] == "https://example.com/jobs/hr-analyst"
        assert job["site"] == "Acme Corp"
        assert job["strategy"] == "hiringcafe"
        assert job["title"] == "HR Analyst"
        assert job["location"] == "Jakarta, Indonesia"
        assert job["description"] == "People ops and HRIS."


class TestPersist:
    def test_insert_and_duplicate(self, tmp_path):
        conn = init_db(tmp_path / "jobs.db")
        html = FIXTURE.read_text(encoding="utf-8")
        jobs = _parse_ssr_html(html).jobs

        inserted, duplicates, skipped = _persist(conn, jobs)
        assert inserted == 1
        assert duplicates == 0
        assert skipped == 0

        inserted, duplicates, skipped = _persist(conn, jobs)
        assert inserted == 0
        assert duplicates == 1
        assert skipped == 0

        row = conn.execute(
            "SELECT url, application_url, site, strategy FROM jobs"
        ).fetchone()
        assert row["url"] == "https://example.com/jobs/hr-analyst"
        assert row["application_url"] == "https://example.com/jobs/hr-analyst"
        assert row["site"] == "Acme Corp"
        assert row["strategy"] == "hiringcafe"
