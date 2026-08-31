from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfWriter

from applypilot import config
from applypilot.apply import launcher
from applypilot.apply import prompt as apply_prompt
from applypilot.database import init_db
from applypilot.preparation import (
    BundleValidationError,
    SelectionError,
    list_preparation_queue,
    list_selected_jobs,
    load_application_bundle,
    record_preparation_failure,
    record_preparation_selection,
    register_application_bundle,
)


def _insert_job(conn, url: str, score: int | None, description: str | None = "JD") -> None:
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, fit_score, full_description, application_url)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (url, "Senior Engineer", "Acme", score, description, f"{url}/apply"),
    )
    conn.commit()


def _bundle(profile_dir: Path, url: str, *, trigger: str = "none", pages: int = 2) -> Path:
    bundle_dir = profile_dir / "resumes" / "applications" / f"acme-senior-engineer-{url.rsplit('/', 1)[-1]}"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "resume.tex").write_text("resume", encoding="utf-8")
    (bundle_dir / "resume.txt").write_text("Senior Engineer", encoding="utf-8")
    resume_writer = PdfWriter()
    for _ in range(pages):
        resume_writer.add_blank_page(width=612, height=792)
    resume_writer.write(bundle_dir / "resume.pdf")
    (bundle_dir / "report.md").write_text("evidence chain", encoding="utf-8")
    cover = {"trigger": trigger}
    if trigger != "none":
        (bundle_dir / "cover-letter.md").write_text("cover", encoding="utf-8")
        (bundle_dir / "cover-letter.txt").write_text("Prepared cover letter", encoding="utf-8")
        cover_writer = PdfWriter()
        cover_writer.add_blank_page(width=612, height=792)
        cover_writer.write(bundle_dir / "cover-letter.pdf")
        cover.update(
            {
                "source": "cover-letter.md",
                "text": "cover-letter.txt",
                "pdf": "cover-letter.pdf",
            }
        )
    manifest = {
        "schema_version": 1,
        "job_url": url,
        "resume": {
            "source": "resume.tex",
            "text": "resume.txt",
            "pdf": "resume.pdf",
            "page_count": pages,
        },
        "report": "report.md",
        "cover_letter": cover,
        "provenance": [
            {
                "requirement": "Engineering experience",
                "status": "supported",
                "sources": ["golden-resume.pdf#page=1"],
            }
        ],
        "validation": {"unslop_applied": True, "factual_provenance": "passed"},
    }
    if pages != 2:
        manifest["resume"]["page_count_justification"] = "The sourced content requires another page."
    path = bundle_dir / "bundle.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_queue_only_contains_described_jobs_at_six_or_higher(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    _insert_job(conn, "https://jobs.example/eligible", 6)
    _insert_job(conn, "https://jobs.example/high", 9)
    _insert_job(conn, "https://jobs.example/low", 5)
    _insert_job(conn, "https://jobs.example/no-description", 8, None)

    assert [job["url"] for job in list_preparation_queue(conn)] == [
        "https://jobs.example/high",
        "https://jobs.example/eligible",
    ]


def test_selection_is_exact_ordered_and_idempotent(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    urls = ["https://jobs.example/one", "https://jobs.example/two"]
    for url in urls:
        _insert_job(conn, url, 7)

    selection_id = record_preparation_selection(urls, conn)
    assert record_preparation_selection(urls, conn) == selection_id
    assert [job["url"] for job in list_selected_jobs(conn)] == urls


@pytest.mark.parametrize(
    ("urls", "message"),
    [
        ([], "at least one explicit"),
        (["https://jobs.example/one", "https://jobs.example/one"], "duplicate"),
        (["https://jobs.example/missing"], "unknown or ineligible"),
    ],
)
def test_selection_rejects_ambiguous_or_ineligible_lists(tmp_path, urls, message):
    conn = init_db(tmp_path / "jobs.db")
    _insert_job(conn, "https://jobs.example/one", 7)

    with pytest.raises(SelectionError, match=message):
        record_preparation_selection(urls, conn)


def test_different_list_cannot_replace_active_selection(tmp_path):
    conn = init_db(tmp_path / "jobs.db")
    for url in ("https://jobs.example/one", "https://jobs.example/two"):
        _insert_job(conn, url, 7)
    record_preparation_selection(["https://jobs.example/one"], conn)

    with pytest.raises(SelectionError, match="active selection"):
        record_preparation_selection(["https://jobs.example/two"], conn)


@pytest.mark.parametrize("trigger", ["none", "posting_request", "upload_field", "email"])
def test_registers_valid_profile_contained_bundle(tmp_path, trigger):
    profile_dir = tmp_path / "profile"
    conn = init_db(profile_dir / "applypilot.db")
    url = "https://jobs.example/one"
    _insert_job(conn, url, 7)
    record_preparation_selection([url], conn)
    manifest = _bundle(profile_dir, url, trigger=trigger)

    bundle = register_application_bundle(url, manifest, conn, profile_dir)

    assert bundle.resume_pdf.name == "resume.pdf"
    assert bundle.cover_letter_trigger == trigger
    assert conn.execute("SELECT application_bundle_path FROM jobs").fetchone()[0] == str(manifest.resolve())
    assert conn.execute("SELECT status FROM preparation_selections").fetchone()[0] == "completed"


def test_multi_job_selection_completes_only_after_every_bundle(tmp_path):
    profile_dir = tmp_path / "profile"
    conn = init_db(profile_dir / "applypilot.db")
    first = "https://jobs.example/one"
    second = "https://jobs.example/two"
    for url in (first, second):
        _insert_job(conn, url, 7)
    record_preparation_selection([first, second], conn)

    register_application_bundle(first, _bundle(profile_dir, first), conn, profile_dir)
    assert conn.execute("SELECT status FROM preparation_selections").fetchone()[0] == "active"
    assert [job["url"] for job in list_selected_jobs(conn)] == [first, second]

    second_manifest = _bundle(profile_dir, second)
    register_application_bundle(second, second_manifest, conn, profile_dir)
    assert conn.execute("SELECT status FROM preparation_selections").fetchone()[0] == "completed"
    assert list_selected_jobs(conn) == []


def test_terminal_failure_closes_selection_and_can_be_retried(tmp_path):
    profile_dir = tmp_path / "profile"
    conn = init_db(profile_dir / "applypilot.db")
    first = "https://jobs.example/one"
    failed = "https://jobs.example/two"
    for url in (first, failed):
        _insert_job(conn, url, 7)
    record_preparation_selection([first, failed], conn)

    register_application_bundle(first, _bundle(profile_dir, first), conn, profile_dir)
    record_preparation_failure(failed, "source resume could not support a required claim", conn)

    assert conn.execute("SELECT status FROM preparation_selections").fetchone()[0] == "completed_with_failures"
    failure = conn.execute(
        "SELECT status, failure_reason FROM preparation_selection_jobs WHERE job_url = ?",
        (failed,),
    ).fetchone()
    assert tuple(failure) == ("failed", "source resume could not support a required claim")
    assert list_selected_jobs(conn) == []
    assert record_preparation_selection([failed], conn) == 2


def test_idempotent_write_cannot_bypass_current_selection(tmp_path):
    profile_dir = tmp_path / "profile"
    conn = init_db(profile_dir / "applypilot.db")
    first = "https://jobs.example/one"
    second = "https://jobs.example/two"
    for url in (first, second):
        _insert_job(conn, url, 7)
    first_manifest = _bundle(profile_dir, first)
    record_preparation_selection([first], conn)
    register_application_bundle(first, first_manifest, conn, profile_dir)
    record_preparation_selection([second], conn)

    with pytest.raises(SelectionError, match="not in the active"):
        register_application_bundle(first, first_manifest, conn, profile_dir)


def test_bundle_write_rejects_job_outside_selection(tmp_path):
    profile_dir = tmp_path / "profile"
    conn = init_db(profile_dir / "applypilot.db")
    selected = "https://jobs.example/selected"
    other = "https://jobs.example/other"
    for url in (selected, other):
        _insert_job(conn, url, 7)
    record_preparation_selection([selected], conn)

    with pytest.raises(SelectionError, match="not in the active"):
        register_application_bundle(other, _bundle(profile_dir, other), conn, profile_dir)


def test_bundle_must_stay_inside_active_profile(tmp_path):
    profile_dir = tmp_path / "profile"
    other_profile = tmp_path / "pipin"
    conn = init_db(profile_dir / "applypilot.db")
    url = "https://jobs.example/one"
    _insert_job(conn, url, 7)
    record_preparation_selection([url], conn)

    with pytest.raises(BundleValidationError, match="inside"):
        register_application_bundle(url, _bundle(other_profile, url), conn, profile_dir)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.update(job_url="https://jobs.example/wrong"), "job_url"),
        (lambda data: data["validation"].update(unslop_applied=False), "unslop"),
        (lambda data: data["validation"].update(factual_provenance="failed"), "provenance"),
        (lambda data: data["cover_letter"].update(trigger="sometimes"), "cover letter trigger"),
    ],
)
def test_bundle_rejects_invalid_manifest(tmp_path, mutate, message):
    profile_dir = tmp_path / "profile"
    url = "https://jobs.example/one"
    manifest = _bundle(profile_dir, url)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    mutate(data)
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(BundleValidationError, match=message):
        load_application_bundle(manifest, profile_dir=profile_dir, expected_url=url)


def test_bundle_rejects_declared_page_count_that_differs_from_pdf(tmp_path):
    profile_dir = tmp_path / "profile"
    url = "https://jobs.example/one"
    manifest = _bundle(profile_dir, url)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["resume"]["page_count"] = 1
    data["resume"]["page_count_justification"] = "Deliberate test mismatch"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(BundleValidationError, match="PDF has 2 page"):
        load_application_bundle(manifest, profile_dir=profile_dir, expected_url=url)


def test_bundle_digest_detects_changes_after_registration(tmp_path):
    profile_dir = tmp_path / "profile"
    url = "https://jobs.example/one"
    manifest = _bundle(profile_dir, url)
    bundle = load_application_bundle(manifest, profile_dir=profile_dir, expected_url=url)
    (manifest.parent / "resume.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(BundleValidationError, match="changed after registration"):
        load_application_bundle(
            manifest,
            profile_dir=profile_dir,
            expected_url=url,
            expected_digest=bundle.digest,
        )


def test_apply_acquires_only_prepared_jobs(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "jobs.db")
    prepared = "https://jobs.example/prepared"
    _insert_job(conn, prepared, 6)
    _insert_job(conn, "https://jobs.example/unprepared", 9)
    conn.execute(
        "UPDATE jobs SET application_bundle_path = ? WHERE url = ?",
        (str(tmp_path / "bundle.json"), prepared),
    )
    conn.commit()
    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: (set(), []))
    monkeypatch.setattr("applypilot.config.is_manual_ats", lambda _url: False)

    job = launcher.acquire_job()

    assert job is not None
    assert job["url"] == prepared
    assert job["application_bundle_path"].endswith("bundle.json")


def test_apply_target_acquires_prepared_job_with_null_status(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "jobs.db")
    url = "https://jobs.example/prepared"
    _insert_job(conn, url, 7)
    conn.execute(
        "UPDATE jobs SET application_bundle_path = ? WHERE url = ?",
        (str(tmp_path / "bundle.json"), url),
    )
    conn.commit()
    monkeypatch.setattr(launcher, "get_connection", lambda: conn)
    monkeypatch.setattr("applypilot.config.is_manual_ats", lambda _url: False)

    job = launcher.acquire_job(target_url=url)

    assert job is not None
    assert job["url"] == url


@pytest.mark.parametrize("trigger", ["none", "upload_field"])
def test_apply_loads_resume_and_conditional_cover_from_manifest(tmp_path, monkeypatch, trigger):
    profile_dir = tmp_path / "profile"
    url = "https://jobs.example/one"
    manifest = _bundle(profile_dir, url, trigger=trigger)
    worker_dir = profile_dir / "apply-workers"
    profile = {
        "personal": {
            "full_name": "Denny Dharmawan",
            "email": "denny@example.com",
            "phone": "+62 8123",
            "city": "Jakarta",
            "country": "Indonesia",
        },
        "work_authorization": {
            "legally_authorized_to_work": True,
            "require_sponsorship": False,
        },
        "compensation": {"salary_expectation": "25000000", "salary_currency": "IDR"},
    }
    monkeypatch.setattr(config, "APP_DIR", profile_dir)
    monkeypatch.setattr(config, "APPLY_WORKER_DIR", worker_dir)
    monkeypatch.setattr(config, "load_profile", lambda: profile)
    monkeypatch.setattr(config, "load_search_config", dict)

    built = apply_prompt.build_prompt(
        {
            "url": url,
            "title": "Senior Engineer",
            "site": "Acme",
            "application_url": f"{url}/apply",
            "fit_score": 7,
            "application_bundle_path": str(manifest),
        },
        dry_run=True,
    )

    assert (worker_dir / "current" / "Denny_Dharmawan_Resume.pdf").is_file()
    cover_upload = worker_dir / "current" / "Denny_Dharmawan_Cover_Letter.pdf"
    assert cover_upload.is_file() is (trigger == "upload_field")
    assert (
        "== COVER LETTER TEXT (paste if text field, upload PDF if file field) ==\n"
        "Prepared cover letter" in built
    ) is (
        trigger == "upload_field"
    )


def _cli(profile_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["APPLYPILOT_DIR"] = str(profile_dir)
    return subprocess.run(
        [sys.executable, "-m", "applypilot", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_prepare_cli_requires_explicit_selection_and_registers_bundle(tmp_path):
    profile_dir = tmp_path / "profile"
    db = profile_dir / "applypilot.db"
    conn = init_db(db)
    url = "https://jobs.example/one"
    _insert_job(conn, url, 7)
    conn.close()

    missing = _cli(profile_dir, "prepare-select")
    assert missing.returncode != 0

    selected = _cli(profile_dir, "prepare-select", "--url", url)
    assert selected.returncode == 0, selected.stdout + selected.stderr
    selected_rows = _cli(profile_dir, "prepare-selected")
    assert json.loads(selected_rows.stdout.strip())["url"] == url

    manifest = _bundle(profile_dir, url)
    written = _cli(profile_dir, "prepare-write", "--url", url, "--bundle", str(manifest))
    assert written.returncode == 0, written.stdout + written.stderr
    row = sqlite3.connect(db).execute(
        "SELECT application_bundle_path FROM jobs WHERE url = ?", (url,)
    ).fetchone()
    assert row == (str(manifest.resolve()),)
