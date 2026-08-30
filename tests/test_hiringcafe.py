from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

from applypilot.database import init_db
from applypilot.discovery.hiringcafe import (
    DiscoverLane,
    DiscoverLaneConfigError,
    DiscoverLanes,
    DiscoverRequest,
    EmptyQueryError,
    Query,
    _crawl,
    _parse_ssr_html,
    _persist,
    _Search,
    parse_run_query,
)

FIXTURE = Path(__file__).parent / "fixtures" / "hiringcafe_ssr.html"


def _write_profile(path: Path, lanes: object) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "profile.json").write_text(
        json.dumps({"preferences": {"discover_lanes": lanes}}),
        encoding="utf-8",
    )


def _run_cli(profile_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["APPLYPILOT_DIR"] = str(profile_dir)
    return subprocess.run(
        [sys.executable, "-m", "applypilot", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _request(*lanes: DiscoverLane) -> DiscoverRequest:
    return DiscoverRequest(
        query=Query.parse("human resource"),
        lanes=DiscoverLanes(frozenset(lanes)),
    )


def _ssr_html(hits: list[dict], *, last: bool) -> str:
    payload = {"props": {"pageProps": {"ssrHits": hits, "ssrIsLastPage": last}}}
    return (
        "<!DOCTYPE html><html><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        "</body></html>"
    )


def _hit(
    *,
    apply_url: str | None = "https://example.com/jobs/hr-analyst",
    title: str = "HR Analyst",
    company: str | None = "Acme Corp",
) -> dict:
    v5: dict = {
        "formatted_workplace_location": "Jakarta, Indonesia",
        "requirements_summary": "People ops.",
    }
    if company is not None:
        v5["company_name"] = company
    hit: dict = {
        "objectID": "job",
        "job_information": {"title": title},
        "v5_processed_job_data": v5,
    }
    if apply_url is not None:
        hit["apply_url"] = apply_url
    return hit


class _ScriptedClient:
    def __init__(self, pages: dict[int, str]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def get(self, url: str):
        self.urls.append(url)
        page = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["page"][0])
        return SimpleNamespace(status_code=200, text=self.pages[page])


class TestQueryParse:
    @pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
    def test_rejects_empty(self, raw):
        with pytest.raises(EmptyQueryError):
            Query.parse(raw)

    def test_accepts_stripped_keywords(self):
        q = Query.parse("  human resource  ")
        assert q.text == "human resource"


class TestParseRunQuery:
    def test_requires_query_only_when_discover_runs(self, tmp_path):
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(
            json.dumps({"preferences": {"discover_lanes": ["jakarta"]}}),
            encoding="utf-8",
        )
        with pytest.raises(EmptyQueryError):
            parse_run_query(None, ["discover"], profile_path=profile_path)

        with pytest.raises(EmptyQueryError):
            parse_run_query("   ", ["discover", "enrich"], profile_path=profile_path)

        assert parse_run_query(None, ["enrich", "score"], profile_path=profile_path) is None
        assert parse_run_query("ignored", ["score"], profile_path=profile_path) is None

    def test_returns_request_when_discover_runs(self, tmp_path):
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(
            json.dumps({"preferences": {"discover_lanes": ["indonesia_eligible_remote"]}}),
            encoding="utf-8",
        )
        request = parse_run_query("backend", ["discover"], profile_path=profile_path)
        assert isinstance(request, DiscoverRequest)
        assert request.query.text == "backend"
        assert request.lanes.values == frozenset({DiscoverLane.INDONESIA_ELIGIBLE_REMOTE})

    @pytest.mark.parametrize(
        ("profile", "error"),
        [
            ({}, "missing preferences.discover_lanes"),
            ({"preferences": {"discover_lanes": []}}, "must not be empty"),
            ({"preferences": {"discover_lanes": "jakarta"}}, "must be a list"),
            (
                {"preferences": {"discover_lanes": ["jakarta", "jakarta"]}},
                "must not contain duplicates",
            ),
            (
                {"preferences": {"discover_lanes": ["moon"]}},
                "unknown value 'moon'",
            ),
        ],
    )
    def test_rejects_invalid_lane_config(self, tmp_path, profile, error):
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")

        with pytest.raises(DiscoverLaneConfigError) as exc_info:
            parse_run_query("backend", ["discover"], profile_path=profile_path)

        message = str(exc_info.value)
        assert str(profile_path) in message
        assert error in message
        assert "jakarta, indonesia_eligible_remote" in message

    @pytest.mark.parametrize(
        ("contents", "error"),
        [
            (None, "profile file is missing"),
            ("{", "profile file is not valid JSON"),
        ],
    )
    def test_rejects_unreadable_profile(self, tmp_path, contents, error):
        profile_path = tmp_path / "profile.json"
        if contents is not None:
            profile_path.write_text(contents, encoding="utf-8")

        with pytest.raises(DiscoverLaneConfigError) as exc_info:
            parse_run_query("backend", ["discover"], profile_path=profile_path)

        message = str(exc_info.value)
        assert str(profile_path) in message
        assert error in message
        assert "jakarta, indonesia_eligible_remote" in message


class TestSearchState:
    @pytest.mark.parametrize(
        ("discover_request", "workplace_types", "flexible_regions"),
        [
            (
                _request(DiscoverLane.JAKARTA),
                ["Remote", "Hybrid", "Onsite"],
                [],
            ),
            (
                _request(DiscoverLane.INDONESIA_ELIGIBLE_REMOTE),
                ["Remote"],
                ["anywhere_in_continent", "anywhere_in_world"],
            ),
            (
                _request(
                    DiscoverLane.JAKARTA,
                    DiscoverLane.INDONESIA_ELIGIBLE_REMOTE,
                ),
                ["Remote", "Hybrid", "Onsite"],
                ["anywhere_in_continent", "anywhere_in_world"],
            ),
        ],
    )
    def test_encodes_selected_lanes(self, discover_request, workplace_types, flexible_regions):
        state = json.loads(_Search.compile(discover_request).search_state_json())
        loc = state["locations"][0]
        assert loc["id"] == "NhY1yZQBoEtHp_8UErPW"
        assert loc["workplace_types"] == workplace_types
        assert loc["options"]["flexible_regions"] == flexible_regions
        assert "anywhere_in_country" not in loc["options"]["flexible_regions"]
        assert state["workplaceTypes"] == workplace_types
        assert state["searchQuery"] == "human resource"
        assert state["dateFetchedPastNDays"] == 3
        assert "page" not in state


class TestParseSsrHtml:
    def test_maps_fixture_hits(self):
        html = FIXTURE.read_text(encoding="utf-8")
        page = _parse_ssr_html(html)

        assert page.is_last_page is True
        assert page.raw_hits == 2
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


class TestSearchPageUrl:
    def test_first_page_is_zero(self):
        url = _Search.compile(_request(DiscoverLane.JAKARTA)).url_for_page(0)
        assert urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["page"] == ["0"]


class TestHitMapping:
    def test_skips_hit_without_employer(self):
        page = _parse_ssr_html(
            _ssr_html([_hit(company=None), _hit(company="  ")], last=True)
        )
        assert page.raw_hits == 2
        assert page.jobs == ()


class TestCrawl:
    def test_continues_when_filtered_jobs_empty(self, tmp_path):
        conn = init_db(tmp_path / "jobs.db")
        client = _ScriptedClient(
            {
                0: _ssr_html([_hit(apply_url=None)], last=False),
                1: _ssr_html(
                    [_hit(apply_url="https://example.com/jobs/kept")],
                    last=True,
                ),
            }
        )
        result = _crawl(_Search.compile(_request(DiscoverLane.JAKARTA)), conn, client)

        assert [int(urllib.parse.parse_qs(urllib.parse.urlparse(u).query)["page"][0]) for u in client.urls] == [
            0,
            1,
        ]
        assert result.pages == 2
        assert result.inserted == 1
        row = conn.execute("SELECT url FROM jobs").fetchone()
        assert row["url"] == "https://example.com/jobs/kept"

    def test_stops_when_raw_hits_empty(self, tmp_path):
        conn = init_db(tmp_path / "jobs.db")
        client = _ScriptedClient(
            {
                0: _ssr_html([], last=False),
                1: _ssr_html(
                    [_hit(apply_url="https://example.com/jobs/should-not-fetch")],
                    last=True,
                ),
            }
        )
        result = _crawl(_Search.compile(_request(DiscoverLane.JAKARTA)), conn, client)

        assert result.pages == 1
        assert result.inserted == 0
        assert len(client.urls) == 1


class TestCliDiscover:
    def test_dry_run_requires_query(self, tmp_path):
        _write_profile(tmp_path, ["jakarta"])
        proc = _run_cli(tmp_path, "run", "discover", "--dry-run")
        assert proc.returncode == 1
        assert "Discover requires --query" in proc.stdout + proc.stderr

    @pytest.mark.parametrize(
        ("lanes", "expected"),
        [
            (["jakarta"], "jakarta"),
            (["indonesia_eligible_remote"], "indonesia_eligible_remote"),
        ],
    )
    def test_dry_run_uses_active_profile(self, tmp_path, lanes, expected):
        _write_profile(tmp_path, lanes)
        proc = _run_cli(
            tmp_path,
            "run",
            "discover",
            "--dry-run",
            "--query",
            "human resource",
        )
        assert proc.returncode == 0
        assert "discover query: human resource" in proc.stdout
        assert f"discover lanes: {expected}" in proc.stdout
        conn = sqlite3.connect(tmp_path / "applypilot.db")
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0

    def test_rejects_invalid_profile_before_discovery(self, tmp_path):
        _write_profile(tmp_path, [])
        proc = _run_cli(
            tmp_path,
            "run",
            "discover",
            "--query",
            "human resource",
        )

        assert proc.returncode == 1
        output = proc.stdout + proc.stderr
        assert "must not be empty" in output
        assert "profile.json" in output
        assert "HiringCafe discover" not in output
