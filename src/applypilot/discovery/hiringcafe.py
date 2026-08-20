"""HiringCafe SSR job discovery."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from applypilot.database import get_connection, init_db

log = logging.getLogger(__name__)

_JAKARTA_PLACE_ID = "NhY1yZQBoEtHp_8UErPW"
_WORKPLACE_TYPES = ("Remote", "Hybrid", "Onsite")
_FLEXIBLE_REGIONS = ("anywhere_in_continent", "anywhere_in_world")
_RECENCY_DAYS = 3
_SSR_ORIGIN = "https://hiringcafe.com"
_MAX_PAGES = 200
_STRATEGY = "hiringcafe"
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

_COMPENSATION_FIELDS = (
    "yearly_min_compensation",
    "yearly_max_compensation",
    "monthly_min_compensation",
    "monthly_max_compensation",
    "weekly_min_compensation",
    "weekly_max_compensation",
    "hourly_min_compensation",
    "hourly_max_compensation",
    "bi-weekly_min_compensation",
    "bi-weekly_max_compensation",
    "daily_min_compensation",
    "daily_max_compensation",
)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


class EmptyQueryError(ValueError):
    """Discover ran without a non-empty --query."""


class DiscoverError(RuntimeError):
    """SSR fetch or parse failed."""


@dataclass(frozen=True, slots=True)
class Query:
    text: str

    @classmethod
    def parse(cls, raw: str | None) -> Query:
        if raw is None:
            raise EmptyQueryError(
                "Discover requires --query with non-empty keywords"
            )
        text = str(raw).strip()
        if not text:
            raise EmptyQueryError(
                "Discover requires --query with non-empty keywords"
            )
        return cls(text)


@dataclass(frozen=True, slots=True)
class DiscoverResult:
    pages: int
    fetched: int
    inserted: int
    duplicates: int
    skipped: int


def parse_run_query(raw: str | None, ordered_stages: Sequence[str]) -> Query | None:
    if "discover" not in ordered_stages:
        return None
    return Query.parse(raw)


@dataclass(frozen=True, slots=True)
class _Search:
    query: Query

    @classmethod
    def compile(cls, query: Query) -> _Search:
        return cls(query=query)

    def search_state_json(self) -> str:
        state = {
            "locations": [
                {
                    "id": _JAKARTA_PLACE_ID,
                    "types": ["administrative_area_level_1"],
                    "address_components": [
                        {
                            "long_name": "Jakarta",
                            "short_name": "04",
                            "types": ["administrative_area_level_1"],
                        },
                        {
                            "long_name": "Indonesia",
                            "short_name": "ID",
                            "types": ["country"],
                        },
                    ],
                    "formatted_address": "Jakarta, Indonesia",
                    "population": 10609681,
                    "workplace_types": list(_WORKPLACE_TYPES),
                    "options": {"flexible_regions": list(_FLEXIBLE_REGIONS)},
                }
            ],
            "workplaceTypes": list(_WORKPLACE_TYPES),
            "searchQuery": self.query.text,
            "dateFetchedPastNDays": _RECENCY_DAYS,
        }
        return json.dumps(state, separators=(",", ":"))

    def url_for_page(self, page: int) -> str:
        encoded = urllib.parse.quote(self.search_state_json(), safe="")
        return f"{_SSR_ORIGIN}/?searchState={encoded}&page={page}"


@dataclass(frozen=True, slots=True)
class _ParsedPage:
    jobs: tuple[dict[str, Any], ...]
    is_last_page: bool


def _valid_http_url(value: str | None) -> str | None:
    if not value:
        return None
    url = value.strip()
    if url.startswith(("http://", "https://")):
        return url
    return None


def _format_compensation(v5: dict[str, Any]) -> str | None:
    values = [
        v5.get(field)
        for field in _COMPENSATION_FIELDS
        if v5.get(field) is not None
    ]
    if not values:
        return None
    currency = v5.get("listed_compensation_currency") or ""
    frequency = v5.get("listed_compensation_frequency") or ""
    mins = [v5.get(f) for f in _COMPENSATION_FIELDS if f.endswith("_min_compensation")]
    maxs = [v5.get(f) for f in _COMPENSATION_FIELDS if f.endswith("_max_compensation")]
    lo = next((v for v in mins if v is not None), None)
    hi = next((v for v in maxs if v is not None), None)
    if lo is not None and hi is not None and lo != hi:
        body = f"{_format_amount(lo)} - {_format_amount(hi)}"
    elif lo is not None:
        body = _format_amount(lo)
    elif hi is not None:
        body = _format_amount(hi)
    else:
        body = _format_amount(values[0])
    suffix = " ".join(part for part in (currency, frequency) if part)
    return f"{body} {suffix}".strip() if suffix else body


def _format_amount(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and abs(value) >= 1000:
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _flatten_hits(raw_hits: object) -> list[dict[str, Any]]:
    if not isinstance(raw_hits, list):
        return []
    flat: list[dict[str, Any]] = []
    for item in raw_hits:
        if not isinstance(item, dict):
            continue
        nested = item.get("jobs") or item.get("job_cards")
        if isinstance(nested, list) and nested:
            for child in nested:
                if isinstance(child, dict):
                    flat.append(child)
        else:
            flat.append(item)
    return flat


def _hit_to_job(hit: dict[str, Any]) -> dict[str, Any] | None:
    apply_url = _valid_http_url(hit.get("apply_url"))
    if not apply_url:
        return None

    info = hit.get("job_information") or {}
    v5 = hit.get("v5_processed_job_data") or {}
    title = info.get("title") or v5.get("core_job_title")
    if not title or not str(title).strip():
        return None

    company = v5.get("company_name")
    site = str(company).strip() if company else None

    return {
        "url": apply_url,
        "application_url": apply_url,
        "title": str(title).strip(),
        "salary": _format_compensation(v5),
        "description": v5.get("requirements_summary"),
        "location": v5.get("formatted_workplace_location"),
        "site": site,
        "strategy": _STRATEGY,
    }


def _parse_ssr_html(html: str) -> _ParsedPage:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise DiscoverError("SSR response missing __NEXT_DATA__")

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise DiscoverError("SSR __NEXT_DATA__ is not valid JSON") from exc

    page_props = data.get("props", {}).get("pageProps")
    if not isinstance(page_props, dict):
        raise DiscoverError("SSR response missing pageProps")

    raw_hits = page_props.get("ssrHits") or []
    is_last_page = bool(page_props.get("ssrIsLastPage"))

    jobs: list[dict[str, Any]] = []
    for hit in _flatten_hits(raw_hits):
        job = _hit_to_job(hit)
        if job is not None:
            jobs.append(job)

    return _ParsedPage(jobs=tuple(jobs), is_last_page=is_last_page)


def _fetch_ssr(client: httpx.Client, search: _Search, page: int) -> str:
    url = search.url_for_page(page)
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        raise DiscoverError(f"SSR fetch failed for page {page}") from exc
    if response.status_code != 200:
        raise DiscoverError(
            f"SSR fetch returned {response.status_code} for page {page}"
        )
    return response.text


def _persist(
    conn: sqlite3.Connection,
    jobs: Sequence[dict[str, Any]],
) -> tuple[int, int, int]:
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    duplicates = 0
    skipped = 0

    for job in jobs:
        url = job.get("url")
        if not url:
            skipped += 1
            continue
        try:
            conn.execute(
                "INSERT INTO jobs "
                "(url, title, salary, description, location, site, strategy, "
                "discovered_at, application_url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    url,
                    job.get("title"),
                    job.get("salary"),
                    job.get("description"),
                    job.get("location"),
                    job.get("site"),
                    job.get("strategy", _STRATEGY),
                    now,
                    job.get("application_url"),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            duplicates += 1

    conn.commit()
    return inserted, duplicates, skipped


def _crawl(
    search: _Search,
    conn: sqlite3.Connection,
    client: httpx.Client,
) -> DiscoverResult:
    pages = 0
    fetched = 0
    inserted = 0
    duplicates = 0
    skipped = 0

    for page in range(_MAX_PAGES):
        html = _fetch_ssr(client, search, page)
        parsed = _parse_ssr_html(html)
        pages += 1
        fetched += len(parsed.jobs)

        page_inserted, page_duplicates, page_skipped = _persist(conn, parsed.jobs)
        inserted += page_inserted
        duplicates += page_duplicates
        skipped += page_skipped

        if parsed.is_last_page or not parsed.jobs:
            break

    return DiscoverResult(
        pages=pages,
        fetched=fetched,
        inserted=inserted,
        duplicates=duplicates,
        skipped=skipped,
    )


def run_discovery(
    query: Query,
    *,
    conn: sqlite3.Connection | None = None,
) -> DiscoverResult:
    db = conn or get_connection()
    if conn is None:
        init_db()

    search = _Search.compile(query)
    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers=_HTTP_HEADERS,
    ) as client:
        return _crawl(search, db, client)
