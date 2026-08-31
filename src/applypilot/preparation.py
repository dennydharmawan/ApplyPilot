from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from applypilot import config
from applypilot.database import get_connection

MIN_PREPARATION_SCORE = 6
COVER_LETTER_TRIGGERS = frozenset({"none", "posting_request", "upload_field", "email"})


class SelectionError(ValueError):
    pass


class BundleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ApplicationBundle:
    manifest_path: Path
    job_url: str
    resume_source: Path
    resume_text: Path
    resume_pdf: Path
    report: Path
    cover_letter_trigger: str
    cover_letter_source: Path | None
    cover_letter_text: Path | None
    cover_letter_pdf: Path | None
    digest: str


def list_preparation_queue(conn: sqlite3.Connection | None = None) -> list[dict]:
    conn = conn or get_connection()
    rows = conn.execute(
        """
        SELECT url, title, site, fit_score, full_description, application_url,
               score_reasoning, application_bundle_path
        FROM jobs
        WHERE fit_score >= ?
          AND full_description IS NOT NULL
          AND TRIM(full_description) != ''
          AND application_bundle_path IS NULL
        ORDER BY fit_score DESC, url
        """,
        (MIN_PREPARATION_SCORE,),
    ).fetchall()
    return [dict(row) for row in rows]


def _active_selection(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, approved_at FROM preparation_selections WHERE status = 'active'"
    ).fetchone()


def _selection_urls(conn: sqlite3.Connection, selection_id: int) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            """
            SELECT job_url FROM preparation_selection_jobs
            WHERE selection_id = ? ORDER BY position
            """,
            (selection_id,),
        )
    ]


def record_preparation_selection(
    urls: list[str], conn: sqlite3.Connection | None = None
) -> int:
    conn = conn or get_connection()
    if not urls:
        raise SelectionError("Preparation selection requires at least one explicit --url")
    if len(urls) != len(set(urls)):
        raise SelectionError("Preparation selection contains a duplicate URL")

    now = datetime.now(UTC).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        active = _active_selection(conn)
        if active:
            if _selection_urls(conn, active["id"]) == urls:
                conn.rollback()
                return active["id"]
            raise SelectionError(
                "A different active selection already exists; finish it before approving another list"
            )

        placeholders = ",".join("?" for _ in urls)
        eligible = {
            row[0]
            for row in conn.execute(
                f"""
                SELECT url FROM jobs
                WHERE url IN ({placeholders})
                  AND fit_score >= ?
                  AND full_description IS NOT NULL
                  AND TRIM(full_description) != ''
                  AND application_bundle_path IS NULL
                """,
                [*urls, MIN_PREPARATION_SCORE],
            )
        }
        rejected = [url for url in urls if url not in eligible]
        if rejected:
            raise SelectionError(
                "Preparation selection contains unknown or ineligible URL(s): " + ", ".join(rejected)
            )

        cursor = conn.execute(
            "INSERT INTO preparation_selections (status, approved_at) VALUES ('active', ?)",
            (now,),
        )
        selection_id = cursor.lastrowid
        conn.executemany(
            """
            INSERT INTO preparation_selection_jobs (selection_id, job_url, position)
            VALUES (?, ?, ?)
            """,
            [(selection_id, url, position) for position, url in enumerate(urls)],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return int(selection_id)


def list_selected_jobs(conn: sqlite3.Connection | None = None) -> list[dict]:
    conn = conn or get_connection()
    active = _active_selection(conn)
    if not active:
        return []
    rows = conn.execute(
        """
        SELECT j.*, psj.position, psj.status AS preparation_status,
               psj.failure_reason AS preparation_failure,
               psj.prepared_at AS selection_prepared_at
        FROM preparation_selection_jobs psj
        JOIN jobs j ON j.url = psj.job_url
        WHERE psj.selection_id = ?
        ORDER BY psj.position
        """,
        (active["id"],),
    ).fetchall()
    return [dict(row) for row in rows]


def _finish_selection_if_terminal(
    conn: sqlite3.Connection, selection_id: int, completed_at: str
) -> None:
    pending = conn.execute(
        """
        SELECT COUNT(*) FROM preparation_selection_jobs
        WHERE selection_id = ? AND status = 'pending'
        """,
        (selection_id,),
    ).fetchone()[0]
    if pending:
        return
    failed = conn.execute(
        """
        SELECT COUNT(*) FROM preparation_selection_jobs
        WHERE selection_id = ? AND status = 'failed'
        """,
        (selection_id,),
    ).fetchone()[0]
    status = "completed_with_failures" if failed else "completed"
    conn.execute(
        """
        UPDATE preparation_selections
        SET status = ?, completed_at = ? WHERE id = ?
        """,
        (status, completed_at, selection_id),
    )


def _contained_file(bundle_dir: Path, relative_path: object, label: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise BundleValidationError(f"Bundle {label} must be a relative file path")
    candidate = (bundle_dir / relative_path).resolve()
    if not candidate.is_relative_to(bundle_dir):
        raise BundleValidationError(f"Bundle {label} must stay inside its bundle directory")
    if not candidate.is_file():
        raise BundleValidationError(f"Bundle {label} not found: {candidate}")
    return candidate


def _pdf_page_count(path: Path, label: str) -> int:
    try:
        count = len(PdfReader(path).pages)
    except (OSError, PdfReadError, ValueError) as exc:
        raise BundleValidationError(f"Bundle {label} is not a readable PDF: {path}") from exc
    if count < 1:
        raise BundleValidationError(f"Bundle {label} has no pages: {path}")
    return count


def load_application_bundle(
    manifest_path: Path | str,
    *,
    profile_dir: Path | str | None = None,
    expected_url: str | None = None,
    expected_digest: str | None = None,
) -> ApplicationBundle:
    profile = Path(profile_dir or config.APP_DIR).resolve()
    allowed_root = (profile / "resumes" / "applications").resolve()
    manifest = Path(manifest_path).resolve()
    if not manifest.is_relative_to(allowed_root):
        raise BundleValidationError(
            f"Application Bundle must be inside {allowed_root} for the active Profile"
        )
    if not manifest.is_file():
        raise BundleValidationError(f"Bundle manifest not found: {manifest}")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleValidationError(f"Invalid bundle manifest {manifest}: {exc}") from exc

    if data.get("schema_version") != 1:
        raise BundleValidationError("Bundle schema_version must be 1")
    job_url = data.get("job_url")
    if not isinstance(job_url, str) or (expected_url and job_url != expected_url):
        raise BundleValidationError("Bundle job_url does not match the selected job")

    bundle_dir = manifest.parent.resolve()
    resume = data.get("resume")
    if not isinstance(resume, dict):
        raise BundleValidationError("Bundle resume must be an object")
    resume_source = _contained_file(bundle_dir, resume.get("source"), "resume source")
    resume_text = _contained_file(bundle_dir, resume.get("text"), "resume text")
    resume_pdf = _contained_file(bundle_dir, resume.get("pdf"), "resume PDF")
    actual_page_count = _pdf_page_count(resume_pdf, "resume PDF")
    page_count = resume.get("page_count")
    if not isinstance(page_count, int) or page_count < 1:
        raise BundleValidationError("Bundle resume page_count must be a positive integer")
    if page_count != actual_page_count:
        raise BundleValidationError(
            f"Bundle resume page_count is {page_count}, but the PDF has {actual_page_count} page(s)"
        )
    if page_count != 2 and not str(resume.get("page_count_justification", "")).strip():
        raise BundleValidationError("A resume outside the two-page standard needs a page_count_justification")
    report = _contained_file(bundle_dir, data.get("report"), "evidence report")

    provenance = data.get("provenance")
    if not isinstance(provenance, list) or not provenance:
        raise BundleValidationError("Bundle provenance must be a non-empty list")
    for index, entry in enumerate(provenance):
        if not isinstance(entry, dict) or not str(entry.get("requirement", "")).strip():
            raise BundleValidationError(f"Bundle provenance entry {index} needs a requirement")
        status = entry.get("status")
        if status not in {"supported", "partial", "gap"}:
            raise BundleValidationError(f"Bundle provenance entry {index} has an invalid status")
        sources = entry.get("sources")
        if not isinstance(sources, list) or any(not isinstance(source, str) or not source.strip() for source in sources):
            raise BundleValidationError(f"Bundle provenance entry {index} sources must be a list of paths")
        if status != "gap" and not sources:
            raise BundleValidationError(f"Bundle provenance entry {index} needs a source")

    validation = data.get("validation")
    if not isinstance(validation, dict) or validation.get("unslop_applied") is not True:
        raise BundleValidationError("Bundle validation must confirm the final unslop pass")
    if validation.get("factual_provenance") != "passed":
        raise BundleValidationError("Bundle factual provenance validation must be passed")

    cover = data.get("cover_letter")
    if not isinstance(cover, dict):
        raise BundleValidationError("Bundle cover_letter must be an object")
    trigger = cover.get("trigger")
    if trigger not in COVER_LETTER_TRIGGERS:
        raise BundleValidationError(
            "Invalid cover letter trigger; accepted values: " + ", ".join(sorted(COVER_LETTER_TRIGGERS))
        )
    cover_source = None
    cover_text = None
    cover_pdf = None
    if trigger == "none":
        if cover.get("source") or cover.get("pdf"):
            raise BundleValidationError("Cover letter files require a posting, upload, or email trigger")
    else:
        cover_source = _contained_file(bundle_dir, cover.get("source"), "cover letter source")
        cover_text = _contained_file(bundle_dir, cover.get("text"), "cover letter text")
        cover_pdf = _contained_file(bundle_dir, cover.get("pdf"), "cover letter PDF")
        _pdf_page_count(cover_pdf, "cover letter PDF")

    digest = hashlib.sha256()
    for path in [
        manifest,
        resume_source,
        resume_text,
        resume_pdf,
        report,
        cover_source,
        cover_text,
        cover_pdf,
    ]:
        if path:
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
    bundle_digest = digest.hexdigest()
    if expected_digest and bundle_digest != expected_digest:
        raise BundleValidationError("Application Bundle changed after registration")

    return ApplicationBundle(
        manifest_path=manifest,
        job_url=job_url,
        resume_source=resume_source,
        resume_text=resume_text,
        resume_pdf=resume_pdf,
        report=report,
        cover_letter_trigger=trigger,
        cover_letter_source=cover_source,
        cover_letter_text=cover_text,
        cover_letter_pdf=cover_pdf,
        digest=bundle_digest,
    )


def register_application_bundle(
    url: str,
    manifest_path: Path | str,
    conn: sqlite3.Connection | None = None,
    profile_dir: Path | str | None = None,
) -> ApplicationBundle:
    conn = conn or get_connection()
    bundle = load_application_bundle(
        manifest_path,
        profile_dir=profile_dir,
        expected_url=url,
    )
    now = datetime.now(UTC).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        active = _active_selection(conn)
        existing = conn.execute(
            "SELECT application_bundle_path, application_bundle_digest FROM jobs WHERE url = ?",
            (url,),
        ).fetchone()
        if not active:
            was_selected = conn.execute(
                """
                SELECT 1 FROM preparation_selection_jobs
                WHERE job_url = ? AND prepared_at IS NOT NULL LIMIT 1
                """,
                (url,),
            ).fetchone()
            if was_selected and existing and existing[0] == str(bundle.manifest_path) and existing[1] == bundle.digest:
                conn.rollback()
                return bundle
            raise SelectionError(f"Job is not in the active Preparation selection: {url}")
        if url not in _selection_urls(conn, active["id"]):
            raise SelectionError(f"Job is not in the active Preparation selection: {url}")
        conn.execute(
            """
            UPDATE jobs SET application_bundle_path = ?, application_bundle_digest = ?, prepared_at = ?
            WHERE url = ?
            """,
            (str(bundle.manifest_path), bundle.digest, now, url),
        )
        conn.execute(
            """
            UPDATE preparation_selection_jobs
            SET status = 'prepared', failure_reason = NULL, prepared_at = ?
            WHERE selection_id = ? AND job_url = ?
            """,
            (now, active["id"], url),
        )
        _finish_selection_if_terminal(conn, active["id"], now)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return bundle


def record_preparation_failure(
    url: str,
    reason: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    conn = conn or get_connection()
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise SelectionError("Preparation failure requires a concrete reason")
    now = datetime.now(UTC).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        active = _active_selection(conn)
        if not active or url not in _selection_urls(conn, active["id"]):
            raise SelectionError(f"Job is not in the active Preparation selection: {url}")
        conn.execute(
            """
            UPDATE preparation_selection_jobs
            SET status = 'failed', failure_reason = ?, prepared_at = NULL
            WHERE selection_id = ? AND job_url = ?
            """,
            (normalized_reason, active["id"], url),
        )
        _finish_selection_if_terminal(conn, active["id"], now)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
