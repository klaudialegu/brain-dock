"""The 10-item Safari checklist, one test per item, in WebKit (Safari's engine).

Tests that write use their own uniquely named rows, so they don't depend on each other's
order. Every test's page also fails on any CSP violation, console error or uncaught
error (the page fixture in conftest.py).
"""

import re
import secrets

import pytest
from playwright.sync_api import expect

from e2e.support import (
    PAGES,
    applications_table,
    open_named_page,
    saved_section,
    settle,
    sideways_overflow,
)

NARROW = {"width": 375, "height": 812}


def unique(label: str) -> str:
    return f"E2E {label} {secrets.token_hex(4)}"


def save_job(page, company: str, role: str, saved_on: str | None = None) -> None:
    page.goto("/applications/saved/new")
    page.locator("input[name=company]").fill(company)
    page.locator("input[name=role_title]").fill(role)
    if saved_on:
        page.locator("input[name=interested_on]").fill(saved_on)
    page.get_by_role("button", name="Save job").click()
    expect(page).to_have_url(re.compile(r"/applications$"))


def saved_row(page, role: str):
    return saved_section(page).locator("tbody tr", has_text=role)


def mark_applied(page, role: str, applied_on: str) -> None:
    row = saved_row(page, role)
    row.locator("input[type=date]").fill(applied_on)
    row.get_by_role("button", name=re.compile("^Mark applied")).click()


def test_01_saved_jobs_kept_out_of_table_and_stats(page):
    page.goto("/applications")
    stats_before = page.locator("section.stats").inner_text()
    chart_before = page.locator("#pipeline-data").text_content()
    rows_before = applications_table(page).locator("tbody tr").count()

    company, role = unique("Co"), unique("Saved role")
    save_job(page, company, role)

    section = saved_section(page)
    expect(section.get_by_role("heading", name="Saved jobs")).to_be_visible()
    expect(saved_row(page, role)).to_have_count(1)
    expect(applications_table(page).get_by_text(role)).to_have_count(0)
    expect(applications_table(page).locator("tbody tr")).to_have_count(rows_before)
    assert page.locator("section.stats").inner_text() == stats_before
    assert page.locator("#pipeline-data").text_content() == chart_before


def test_02_save_a_job_nav_entry_and_button(page):
    page.goto("/applications")
    # The module's own menu on its pages (the rail lists modules, ADR 0016).
    module_nav = page.get_by_role("navigation", name="Career Radar")
    nav_link = module_nav.get_by_role("link", name="Save a job")
    expect(nav_link).to_be_visible()
    button = page.locator("a.button", has_text="Save a job")
    expect(button).to_be_visible()

    nav_link.click()
    expect(page).to_have_url(re.compile(r"/applications/saved/new$"))
    expect(page.get_by_role("heading", level=1, name="Save a job")).to_be_visible()

    page.goto("/applications")
    page.locator("a.button", has_text="Save a job").click()
    expect(page.get_by_role("heading", level=1, name="Save a job")).to_be_visible()


def test_03_save_a_job_lands_in_saved_jobs(page):
    company, role = unique("Co"), unique("Role")
    save_job(page, company, role, saved_on="2026-01-10")
    row = saved_row(page, role)
    expect(row).to_have_count(1)
    expect(row).to_contain_text(company)
    expect(row).to_contain_text("2026-01-10")


def test_04_bad_link_or_no_company_shows_field_errors_and_saves_nothing(page, recorder):
    page.goto("/applications")
    saved_before = saved_section(page).locator("tbody tr").count()

    role = unique("Bad role")
    recorder.expect_error_page(400)
    page.goto("/applications/saved/new")
    # Inputs WebKit's own checks accept but the server rejects: spaces pass `required`,
    # and ftp:// is a valid URL for type=url.
    page.locator("input[name=company]").fill("   ")
    page.locator("input[name=role_title]").fill(role)
    page.locator("input[name=link]").fill("ftp://example.com")
    page.get_by_role("button", name="Save job").click()

    for name in ("company", "link"):
        expect(page.locator(f"input[name={name}]")).to_have_attribute("aria-invalid", "true")
        expect(page.locator(f"#{name}-error.field-error")).to_be_visible()
    expect(page.locator("input[name=role_title]")).not_to_have_attribute("aria-invalid", "true")
    assert list(recorder.error_pages.values()) == [400]  # the form really came back as a 400

    page.goto("/applications")
    expect(saved_section(page).locator("tbody tr")).to_have_count(saved_before)
    expect(page.get_by_text(role)).to_have_count(0)


def test_05_mark_applied_too_early_shows_row_error(page, recorder):
    company, role = unique("Co"), unique("Early role")
    save_job(page, company, role, saved_on="2026-01-10")
    recorder.expect_error_page(400)
    mark_applied(page, role, "2026-01-09")

    row = saved_row(page, role)
    expect(row.locator(".field-error")).to_contain_text("on or after the day it was saved")
    expect(row.locator("input[type=date]")).to_have_attribute("aria-invalid", "true")
    expect(applications_table(page).get_by_text(role)).to_have_count(0)
    assert list(recorder.error_pages.values()) == [400]


def test_06_mark_applied_moves_job_to_table_and_opens_edit(page):
    company, role = unique("Co"), unique("Applied role")
    save_job(page, company, role, saved_on="2026-01-10")
    mark_applied(page, role, "2026-01-12")

    expect(page).to_have_url(re.compile(r"/applications$"))
    # exact: the hidden "Edit <role> at <company>" link text contains the role too
    expect(applications_table(page).get_by_text(role, exact=True)).to_have_count(1)
    expect(saved_row(page, role)).to_have_count(0)

    page.get_by_role("link", name=f"Edit {role} at {company}").click()
    expect(page).to_have_url(re.compile(r"/applications/\d+/edit$"))  # a saved job's is a 404
    expect(page.get_by_role("heading", level=1, name="Edit application")).to_be_visible()
    expect(page.locator("input[name=role_title]")).to_have_value(role)


def test_07_company_page_lists_saved_jobs_read_only(page):
    company, role = unique("Co"), unique("Company role")
    save_job(page, company, role)
    saved_row(page, role).get_by_role("link", name=company).click()

    expect(page.get_by_role("heading", level=1, name=company)).to_be_visible()
    section = saved_section(page)
    expect(section.get_by_role("heading", name="Saved jobs")).to_be_visible()
    expect(section.get_by_text(role)).to_be_visible()
    expect(section.locator("form, input, button")).to_have_count(0)


def test_08_inbox_accepted_save_as_interested_prefills_form(page):
    page.goto("/inbox")
    row = page.locator("table.triage tbody tr").first
    cells = row.locator("td")
    title = cells.nth(0).inner_text().strip()
    company = cells.nth(1).inner_text().strip()
    link = (
        cells.nth(0).locator("a").get_attribute("href") if cells.nth(0).locator("a").count() else ""
    )
    row.get_by_role("button", name=re.compile("^Approve")).click()

    accepted = page.locator("section[aria-labelledby=accepted-heading]")
    expect(accepted.get_by_text(f"{title} at {company}")).to_be_visible()
    # The hidden span is absolutely positioned, so the name reads "Save as interested : ...".
    name = re.compile(rf"^Save as interested\s*: {re.escape(title)} at {re.escape(company)}$")
    accepted.get_by_role("link", name=name).click()

    expect(page.get_by_role("heading", level=1, name="Save a job")).to_be_visible()
    expect(page.locator("input[name=company]")).to_have_value(company)
    expect(page.locator("input[name=role_title]")).to_have_value(title)
    expect(page.locator("input[name=link]")).to_have_value(link)


@pytest.mark.parametrize("name", PAGES)
def test_09_narrow_window_nothing_clipped(page, name):
    page.set_viewport_size(NARROW)
    open_named_page(page, name)
    settle(page)
    assert sideways_overflow(page) == 0, f"{name} scrolls sideways at {NARROW['width']} px"


@pytest.mark.parametrize("name", PAGES)
def test_10_no_csp_violations_or_console_errors(page, recorder, name):
    open_named_page(page, name)
    settle(page)
    assert recorder.problems() == []


def test_10_pipeline_chart_draws_under_csp(page, recorder):
    page.goto("/applications")
    # ECharts draws into a canvas inside the chart element once the deferred scripts ran.
    expect(page.locator("#pipeline-chart canvas").first).to_be_attached()
    settle(page)
    assert recorder.problems() == []
