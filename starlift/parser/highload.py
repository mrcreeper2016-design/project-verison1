"""
HighLoad++ abstracts page: fetch HTML and parse structured talk rows.

Pure parsing helpers (no CSV, no side effects on import).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

import requests
from bs4 import BeautifulSoup

DEFAULT_BASE_URL = "https://highload.ru"

_STYLE_URL_RE = re.compile(r"url\(\s*['\"]?([^'\"]+\/?)['\"]?\s*\)", re.I)


@dataclass(frozen=True)
class RawTalkRecord:
    """One speaker × talk row as scraped from the listing."""

    author: str
    author_avatar: str
    company: str
    title: str
    date: str
    stack: str
    description: str
    link: str


def normalize_record_fields(
    author: str,
    author_avatar: str,
    company: str,
    title: str,
    date: str,
    stack: str,
    description: str,
    link: str,
) -> dict[str, str]:
    """Trim and collapse whitespace; ensure str values (never None)."""
    return {
        "author": " ".join((author or "").split()).strip(),
        "author_avatar": (author_avatar or "").strip(),
        "company": " ".join((company or "").split()).strip(),
        "title": " ".join((title or "").split()).strip(),
        "date": " ".join((date or "").split()).strip(),
        "stack": " ".join((stack or "").replace("\xa0", " ").split()).strip(),
        "description": (description or "").strip(),
        "link": (link or "").strip(),
    }


def fetch_html(
    url: str,
    *,
    timeout: float = 20,
    session: requests.Session | None = None,
) -> str:
    """Load page HTML. Raises on non-200 or request errors."""
    client = session or requests.Session()
    resp = client.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _extract_url_from_style(style: str | None, base_url: str) -> str:
    if not style:
        return ""
    m = _STYLE_URL_RE.search(style)
    if not m:
        return ""
    path = m.group(1).strip()
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("//"):
        return "https:" + path
    if path.startswith("/"):
        return base_url.rstrip("/") + path
    return base_url.rstrip("/") + "/" + path


def _parse_tag_text(el) -> str:
    if el is None:
        return ""
    return el.get_text(separator=" ", strip=True) or ""


def parse_records_from_html(html_text: str, *, base_url: str = DEFAULT_BASE_URL) -> list[dict[str, str]]:
    """
    Parse thesis list into normalized dicts with keys:
    author, author_avatar, company, title, date, stack, description, link.

    Missing blocks in markup are skipped per-report, not fatal for the whole page.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    thesis_list = soup.find("div", class_="thesis__list")
    if thesis_list is None:
        return []

    out: list[dict[str, str]] = []

    for thesis in thesis_list.find_all("div", recursive=False):
        for report in thesis.find_all("div", recursive=False):
            try:
                rows = _parse_one_report(report, base_url=base_url)
                out.extend(rows)
            except Exception:
                continue

    return out


def _parse_one_report(report, *, base_url: str) -> list[dict[str, str]]:
    title_el = report.find("h2", class_="thesis__item-title")
    if title_el is None:
        return []
    title_a = title_el.find("a", class_="thesis__item-title-link")
    if title_a is None or not title_a.get("href"):
        return []

    href = title_a.get("href", "")
    link = href if href.startswith("http") else base_url.rstrip("/") + href
    title_text = title_a.get_text(separator=" ", strip=True) or ""

    stacks: list[str] = []
    tags = report.find("div", class_="thesis__tags")
    if tags is not None:
        for stack in tags.find_all("div", recursive=False):
            t = stack.get_text(separator=" ", strip=True)
            if t:
                stacks.append(t)
    stack_joined = ", ".join(stacks)

    authors_block = report.find("div", class_="thesis__authors")
    if authors_block is None:
        return []

    authors_data: dict[str, dict[str, str]] = {}
    for author in authors_block.find_all("div", class_="thesis__author", recursive=False):
        name_el = author.find("a", class_="thesis__author-name")
        if name_el is None:
            continue
        name = name_el.get_text(separator=" ", strip=True) or ""
        if not name:
            continue
        company_el = author.find("p", class_="thesis__author-company")
        company = _parse_tag_text(company_el)
        img_link = author.find("a", class_="thesis__author-img")
        style = img_link.get("style") if img_link is not None else None
        avatar = _extract_url_from_style(style, base_url)
        authors_data[name] = {"company": company, "avatar": avatar}

    if not authors_data:
        return []

    date = ""
    sched = report.find("a", class_="thesis__item-schedule-text")
    if sched is not None:
        date_text = sched.get_text(separator=" ", strip=True) or ""
        if "," in date_text:
            date = date_text[: date_text.find(",")].strip()
        else:
            date = date_text.strip()

    desc_el = report.find("div", class_="thesis__text")
    description = desc_el.get_text(separator="\n", strip=True) if desc_el else ""

    rows: list[dict[str, str]] = []
    for name, d_author in authors_data.items():
        rows.append(
            normalize_record_fields(
                author=name,
                author_avatar=d_author["avatar"],
                company=d_author["company"],
                title=title_text,
                date=date,
                stack=stack_joined,
                description=description,
                link=link,
            )
        )
    return rows


def record_is_valid(rec: Mapping[str, str]) -> bool:
    """True when row is worth persisting (minimal required fields)."""
    return bool(rec.get("author") and rec.get("title"))
