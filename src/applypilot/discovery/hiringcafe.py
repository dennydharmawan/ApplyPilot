from __future__ import annotations

import json
import logging
import re
import sqlite3
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

from applypilot.config import PROFILE_PATH
from applypilot.database import get_connection, init_db, store_jobs

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
    pass


class DiscoverLaneConfigError(ValueError):
    pass


class SsrFetchError(RuntimeError):
    pass


class SsrParseError(RuntimeError):
    pass


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


class DiscoverLane(str, Enum):
    JAKARTA = "jakarta"
    INDONESIA_ELIGIBLE_REMOTE = "indonesia_eligible_remote"


@dataclass(frozen=True, slots=True)
class DiscoverLanes:
    values: frozenset[DiscoverLane]

    def __post_init__(self) -> None:
        if not isinstance(self.values, frozenset) or any(not isinstance(lane, DiscoverLane) for lane in self.values):
            raise ValueError("DiscoverLanes requires a frozenset of DiscoverLane values")
        if not self.values:
            raise ValueError("DiscoverLanes must not be empty")

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(lane.value for lane in DiscoverLane if lane in self.values)


@dataclass(frozen=True, slots=True)
class DiscoverRequest:
    query: Query
    lanes: DiscoverLanes


@dataclass(frozen=True, slots=True)
class DiscoverResult:
    pages: int
    fetched: int
    inserted: int
    duplicates: int
    skipped: int


def _lane_config_error(profile_path: Path, detail: str) -> DiscoverLaneConfigError:
    accepted = ", ".join(lane.value for lane in DiscoverLane)
    return DiscoverLaneConfigError(
        f"Invalid Discover lane configuration in {profile_path}: {detail}. "
        "Set preferences.discover_lanes to a non-empty list with no duplicates. "
        f"Accepted values: {accepted}"
    )


def _load_discover_lanes(profile_path: Path) -> DiscoverLanes:
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise _lane_config_error(profile_path, "profile file is missing") from exc
    except json.JSONDecodeError as exc:
        raise _lane_config_error(profile_path, "profile file is not valid JSON") from exc

    if not isinstance(profile, dict):
        raise _lane_config_error(profile_path, "profile must be a JSON object")
    preferences = profile.get("preferences")
    if not isinstance(preferences, dict) or "discover_lanes" not in preferences:
        raise _lane_config_error(profile_path, "missing preferences.discover_lanes")

    raw_lanes = preferences["discover_lanes"]
    if not isinstance(raw_lanes, list):
        raise _lane_config_error(profile_path, "preferences.discover_lanes must be a list")
    if not raw_lanes:
        raise _lane_config_error(profile_path, "preferences.discover_lanes must not be empty")

    lanes: list[DiscoverLane] = []
    for raw_lane in raw_lanes:
        try:
            lane = DiscoverLane(raw_lane)
        except (TypeError, ValueError) as exc:
            raise _lane_config_error(profile_path, f"unknown value {raw_lane!r}") from exc
        if lane in lanes:
            raise _lane_config_error(
                profile_path,
                f"preferences.discover_lanes must not contain duplicates ({lane.value!r})",
            )
        lanes.append(lane)
    return DiscoverLanes(frozenset(lanes))


def parse_run_query(
    raw: str | None,
    ordered_stages: Sequence[str],
    *,
    profile_path: Path = PROFILE_PATH,
) -> DiscoverRequest | None:
    if "discover" not in ordered_stages:
        return None
    return DiscoverRequest(
        query=Query.parse(raw),
        lanes=_load_discover_lanes(profile_path),
    )


@dataclass(frozen=True, slots=True)
class _Search:
    request: DiscoverRequest

    @classmethod
    def compile(cls, request: DiscoverRequest) -> _Search:
        return cls(request=request)

    def search_state_json(self) -> str:
        has_jakarta = DiscoverLane.JAKARTA in self.request.lanes.values
        has_remote = DiscoverLane.INDONESIA_ELIGIBLE_REMOTE in self.request.lanes.values
        workplace_types = list(_WORKPLACE_TYPES) if has_jakarta else ["Remote"]
        flexible_regions = list(_FLEXIBLE_REGIONS) if has_remote else []
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
                    "workplace_types": workplace_types,
                    "options": {"flexible_regions": flexible_regions},
                }
            ],
            "workplaceTypes": workplace_types,
            "searchQuery": self.request.query.text,
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
    raw_hits: int


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
    site = str(company).strip() if company else ""
    if not site:
        return None

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
        raise SsrParseError("SSR response missing __NEXT_DATA__")

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SsrParseError("SSR __NEXT_DATA__ is not valid JSON") from exc

    page_props = data.get("props", {}).get("pageProps")
    if not isinstance(page_props, dict):
        raise SsrParseError("SSR response missing pageProps")

    raw_hits = _flatten_hits(page_props.get("ssrHits") or [])
    is_last_page = bool(page_props.get("ssrIsLastPage"))

    jobs: list[dict[str, Any]] = []
    for hit in raw_hits:
        job = _hit_to_job(hit)
        if job is not None:
            jobs.append(job)

    return _ParsedPage(
        jobs=tuple(jobs),
        is_last_page=is_last_page,
        raw_hits=len(raw_hits),
    )


def _fetch_ssr(client: httpx.Client, search: _Search, page: int) -> str:
    url = search.url_for_page(page)
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        raise SsrFetchError(f"SSR fetch failed for page {page}") from exc
    if response.status_code != 200:
        raise SsrFetchError(
            f"SSR fetch returned {response.status_code} for page {page}"
        )
    return response.text


def _persist(
    conn: sqlite3.Connection,
    jobs: Sequence[dict[str, Any]],
) -> tuple[int, int, int]:
    skipped = 0
    storable: list[dict[str, Any]] = []
    for job in jobs:
        if job.get("url"):
            storable.append(job)
        else:
            skipped += 1
    inserted, duplicates = store_jobs(
        conn, storable, site="", strategy=_STRATEGY
    )
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

        if parsed.is_last_page or parsed.raw_hits == 0:
            break
    else:
        log.warning(
            "HiringCafe crawl stopped at %s-page cap before ssrIsLastPage",
            _MAX_PAGES,
        )

    return DiscoverResult(
        pages=pages,
        fetched=fetched,
        inserted=inserted,
        duplicates=duplicates,
        skipped=skipped,
    )


def run_discovery(
    request: DiscoverRequest,
    *,
    conn: sqlite3.Connection | None = None,
) -> DiscoverResult:
    db = conn or get_connection()
    if conn is None:
        init_db()

    search = _Search.compile(request)
    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers=_HTTP_HEADERS,
    ) as client:
        return _crawl(search, db, client)
